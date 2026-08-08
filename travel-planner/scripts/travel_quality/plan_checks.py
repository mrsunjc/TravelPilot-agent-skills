"""Schedule, route, weather, budget, constraint, and return checks."""

from collections import Counter

from .common import finding, parse_date, parse_datetime, time_to_minutes, unique_index


def _window_applies(window, visit_date):
    dates = window.get("dates") or []
    weekdays = window.get("weekdays") or []
    if dates and visit_date.isoformat() not in dates:
        return False
    if weekdays and visit_date.isoweekday() not in weekdays:
        return False
    return True


def _severe_weather(weather, thresholds):
    return (
        float(weather.get("precipitation_probability", 0)) >= float(thresholds.get("precipitation_probability", 70))
        or float(weather.get("wind_speed_kmh", 0)) >= float(thresholds.get("wind_speed_kmh", 40))
        or float(weather.get("temp_max_c", 0)) >= float(thresholds.get("high_temperature_c", 35))
        or float(weather.get("temp_min_c", 0)) <= float(thresholds.get("low_temperature_c", -10))
    )


def _check_constraints(plan, attraction_index):
    findings = []
    constraints = plan.get("user_constraints") or {}
    must_go = set(constraints.get("must_go") or [])
    excluded = set(constraints.get("exclude") or [])
    scheduled = {
        stop.get("attraction_id")
        for day in plan.get("itinerary") or []
        if isinstance(day, dict)
        for stop in day.get("stops") or []
        if isinstance(stop, dict) and stop.get("kind") == "attraction"
    }
    for attraction_id in sorted(must_go - scheduled):
        findings.append(
            finding("CONSTRAINT_MUST_GO_MISSING", "error", "Required attraction is not scheduled: %s" % attraction_id, "$.user_constraints.must_go")
        )
    for attraction_id in sorted(excluded & scheduled):
        findings.append(
            finding("CONSTRAINT_EXCLUDED_SCHEDULED", "error", "Excluded attraction was scheduled: %s" % attraction_id, "$.user_constraints.exclude")
        )
    unknown = (must_go | excluded) - set(attraction_index)
    for attraction_id in sorted(unknown):
        findings.append(
            finding("CONSTRAINT_UNKNOWN_ATTRACTION", "warning", "Constraint references unknown attraction: %s" % attraction_id, "$.user_constraints")
        )
    return findings


def _check_opening_and_reservation(day, day_position, stop, stop_position, attraction):
    findings = []
    base_path = "$.itinerary[%d].stops[%d]" % (day_position, stop_position)
    visit_date = parse_date(day.get("date"))
    arrival = time_to_minutes(stop.get("arrival_time"))
    departure = time_to_minutes(stop.get("departure_time"))
    if visit_date is None:
        findings.append(
            finding("SCHEDULE_DATE_UNVERIFIED", "warning", "Cannot verify opening hours without a visit date", base_path)
        )
    else:
        if visit_date.isoformat() in set(attraction.get("closed_dates") or []):
            findings.append(
                finding("SCHEDULE_CLOSED_DATE", "error", "Attraction is marked closed on the planned date", base_path)
            )
        applicable = [window for window in attraction.get("opening_windows") or [] if _window_applies(window, visit_date)]
        if not applicable:
            findings.append(
                finding("SCHEDULE_NO_OPEN_WINDOW", "error", "No opening window applies to the planned date", base_path)
            )
        elif arrival is not None and departure is not None:
            fits = False
            for window in applicable:
                opening = time_to_minutes(window.get("open"))
                closing = time_to_minutes(window.get("close"))
                last_entry = time_to_minutes(window.get("last_entry")) if window.get("last_entry") else closing
                if opening is not None and closing is not None and arrival >= opening and departure <= closing and arrival <= last_entry:
                    fits = True
                    break
            if not fits:
                findings.append(
                    finding("SCHEDULE_OUTSIDE_OPEN_HOURS", "error", "Visit does not fit an applicable opening window", base_path)
                )

    reservation = attraction.get("reservation") or {}
    if reservation.get("required"):
        status = stop.get("reservation_status") or reservation.get("status")
        if status == "unknown" or not status:
            findings.append(
                finding("RESERVATION_STATUS_UNKNOWN", "error", "Required reservation status is unknown", base_path + ".reservation_status")
            )
        elif status == "to_book":
            deadline = parse_datetime(reservation.get("deadline"))
            generated = parse_datetime(day.get("_generated_at"))
            severity = "error" if deadline and generated and generated >= deadline else "warning"
            findings.append(
                finding("RESERVATION_PENDING", severity, "Required reservation has not been booked", base_path + ".reservation_status")
            )
    return findings


def _check_day(plan, day, day_position, attraction_index, backup_index, weather_by_date, policy):
    findings = []
    stops = day.get("stops") if isinstance(day.get("stops"), list) else []
    legs = day.get("legs") if isinstance(day.get("legs"), list) else []
    path = "$.itinerary[%d]" % day_position
    stop_index, duplicates = unique_index(stops)
    for duplicate, position in duplicates:
        findings.append(finding("SCHEDULE_DUPLICATE_STOP_ID", "error", "Duplicate stop id: %s" % duplicate, "%s.stops[%d].id" % (path, position)))

    visit_minutes = 0
    attraction_stops = 0
    day_start = None
    day_end = None
    for stop_position, stop in enumerate(stops):
        if not isinstance(stop, dict):
            continue
        arrival = time_to_minutes(stop.get("arrival_time"))
        departure = time_to_minutes(stop.get("departure_time"))
        base_path = "%s.stops[%d]" % (path, stop_position)
        if arrival is not None and departure is not None:
            if departure < arrival:
                findings.append(finding("SCHEDULE_NEGATIVE_DURATION", "error", "Stop departure is before arrival", base_path))
            else:
                actual = departure - arrival
                declared = stop.get("duration_minutes")
                if isinstance(declared, (int, float)) and abs(actual - declared) > 10:
                    findings.append(
                        finding("SCHEDULE_DURATION_MISMATCH", "warning", "Declared duration differs from clock time by more than 10 minutes", base_path + ".duration_minutes")
                    )
                day_start = arrival if day_start is None else min(day_start, arrival)
                day_end = departure if day_end is None else max(day_end, departure)
        if stop.get("kind") == "attraction":
            attraction_stops += 1
            visit_minutes += int(stop.get("duration_minutes") or 0)
            attraction_id = stop.get("attraction_id")
            attraction = attraction_index.get(attraction_id)
            if attraction is None:
                findings.append(finding("SCHEDULE_ATTRACTION_NOT_FOUND", "error", "Stop references unknown attraction: %s" % attraction_id, base_path + ".attraction_id"))
            else:
                day_with_context = dict(day)
                day_with_context["_generated_at"] = plan.get("generated_at")
                findings.extend(_check_opening_and_reservation(day_with_context, day_position, stop, stop_position, attraction))

    for position in range(len(stops) - 1):
        current = stops[position]
        following = stops[position + 1]
        if not isinstance(current, dict) or not isinstance(following, dict):
            continue
        current_departure = time_to_minutes(current.get("departure_time"))
        next_arrival = time_to_minutes(following.get("arrival_time"))
        if current_departure is not None and next_arrival is not None and next_arrival < current_departure:
            findings.append(
                finding("SCHEDULE_OVERLAP", "error", "Consecutive stops overlap", "%s.stops[%d]" % (path, position + 1))
            )
        matching = [leg for leg in legs if isinstance(leg, dict) and leg.get("from") == current.get("id") and leg.get("to") == following.get("id")]
        if not matching:
            findings.append(
                finding("ROUTE_LEG_MISSING", "error", "No route leg connects consecutive stops", "%s.legs" % path, {"from": current.get("id"), "to": following.get("id")})
            )
        elif current_departure is not None and next_arrival is not None:
            available = next_arrival - current_departure
            if int(matching[0].get("minutes") or 0) > available:
                findings.append(
                    finding("ROUTE_TIME_DOES_NOT_FIT", "error", "Travel time exceeds the gap between stops", "%s.legs" % path, {"available_minutes": available, "required_minutes": matching[0].get("minutes")})
                )

    evidence_ids = {item.get("id") for item in plan.get("evidence") or [] if isinstance(item, dict)}
    estimated_legs = 0
    for leg_position, leg in enumerate(legs):
        if not isinstance(leg, dict):
            continue
        leg_path = "%s.legs[%d]" % (path, leg_position)
        if leg.get("from") not in stop_index or leg.get("to") not in stop_index:
            findings.append(finding("ROUTE_UNKNOWN_STOP", "error", "Route leg references a stop outside the day", leg_path))
        if leg.get("verified") and not leg.get("evidence_ids"):
            findings.append(finding("ROUTE_VERIFIED_WITHOUT_EVIDENCE", "error", "Verified route leg needs evidence_ids", leg_path + ".evidence_ids"))
        if not leg.get("verified"):
            estimated_legs += 1
            findings.append(
                finding(
                    "ROUTE_ESTIMATED_LEG",
                    "warning",
                    "Route leg is estimated and needs map verification before exact publication",
                    leg_path,
                )
            )
        for evidence_id in leg.get("evidence_ids") or []:
            if evidence_id not in evidence_ids:
                findings.append(finding("ROUTE_EVIDENCE_NOT_FOUND", "error", "Route leg references missing evidence: %s" % evidence_id, leg_path + ".evidence_ids"))

    zone_sequence = []
    for stop in stops:
        zone = stop.get("zone") if isinstance(stop, dict) else None
        if zone and (not zone_sequence or zone_sequence[-1] != zone):
            zone_sequence.append(zone)
    zone_transitions = max(0, len(zone_sequence) - 1)
    if len(zone_sequence) != len(set(zone_sequence)):
        findings.append(finding("ROUTE_BACKTRACK", "error", "Day returns to a previously visited zone", path + ".stops", {"zone_sequence": zone_sequence}))
    if zone_transitions > 1:
        findings.append(finding("ROUTE_TOO_MANY_ZONE_TRANSITIONS", "warning", "Day changes zones more than once", path + ".stops", {"zone_sequence": zone_sequence}))

    intensity = (plan.get("trip") or {}).get("intensity", "normal")
    limits = (policy.get("intensity_limits") or {}).get(intensity, {})
    travel_minutes = sum(int(leg.get("minutes") or 0) for leg in legs if isinstance(leg, dict))
    if visit_minutes > int(limits.get("visit_minutes", 10 ** 9)):
        findings.append(finding("INTENSITY_VISIT_LIMIT", "warning", "Attraction time exceeds intensity guideline", path, {"visit_minutes": visit_minutes}))
    if travel_minutes > int(limits.get("travel_minutes", 10 ** 9)):
        findings.append(finding("INTENSITY_TRAVEL_LIMIT", "warning", "Travel time exceeds intensity guideline", path, {"travel_minutes": travel_minutes}))
    if attraction_stops > int(limits.get("stops", 10 ** 9)):
        findings.append(finding("INTENSITY_STOP_LIMIT", "warning", "Attraction count exceeds intensity guideline", path, {"attraction_stops": attraction_stops}))
    if day_start is not None and day_end is not None and day_end - day_start >= 360 and not any(isinstance(stop, dict) and stop.get("kind") == "meal" for stop in stops):
        findings.append(finding("SCHEDULE_MEAL_BREAK_MISSING", "warning", "Long day has no meal stop", path + ".stops"))

    day_date = day.get("date")
    weather = weather_by_date.get(day_date)
    if weather and _severe_weather(weather, policy.get("weather_thresholds") or {}):
        for stop_position, stop in enumerate(stops):
            attraction = attraction_index.get(stop.get("attraction_id")) if isinstance(stop, dict) else None
            if attraction and attraction.get("outdoor"):
                backup_ids = set(day.get("backup_ids") or []) | set(stop.get("backup_ids") or [])
                valid_backups = [backup_id for backup_id in backup_ids if backup_id in backup_index]
                if not valid_backups:
                    findings.append(
                        finding("WEATHER_BACKUP_REQUIRED", "error", "Outdoor stop has severe weather but no valid backup", "%s.stops[%d]" % (path, stop_position))
                    )

    return findings, {
        "visit_minutes": visit_minutes,
        "travel_minutes": travel_minutes,
        "zone_transitions": zone_transitions,
        "estimated_legs": estimated_legs,
        "legs": len(legs),
    }


def _check_budget(plan, policy):
    findings = []
    budget = plan.get("budget") or {}
    categories = budget.get("categories") if isinstance(budget.get("categories"), list) else []
    names = [item.get("name") for item in categories if isinstance(item, dict)]
    duplicates = [name for name, count in Counter(names).items() if count > 1]
    for name in duplicates:
        findings.append(finding("BUDGET_DUPLICATE_CATEGORY", "error", "Duplicate budget category: %s" % name, "$.budget.categories"))
    required = set(policy.get("required_budget_categories") or [])
    missing = sorted(required - set(names))
    if missing:
        findings.append(finding("BUDGET_CATEGORY_MISSING", "error", "Missing budget categories: %s" % ", ".join(missing), "$.budget.categories"))

    minimum = 0.0
    maximum = 0.0
    for position, item in enumerate(categories):
        if not isinstance(item, dict):
            continue
        low = item.get("min")
        high = item.get("max")
        if isinstance(low, (int, float)) and isinstance(high, (int, float)):
            if low > high:
                findings.append(finding("BUDGET_RANGE_REVERSED", "error", "Budget minimum exceeds maximum", "$.budget.categories[%d]" % position))
            minimum += low
            maximum += high
    total = budget.get("total") or {}
    if isinstance(total.get("min"), (int, float)) and abs(total["min"] - minimum) > 0.01:
        findings.append(finding("BUDGET_TOTAL_MISMATCH", "error", "Budget total minimum does not equal category sum", "$.budget.total.min", {"expected": minimum}))
    if isinstance(total.get("max"), (int, float)) and abs(total["max"] - maximum) > 0.01:
        findings.append(finding("BUDGET_TOTAL_MISMATCH", "error", "Budget total maximum does not equal category sum", "$.budget.total.max", {"expected": maximum}))
    contingency = next((item for item in categories if isinstance(item, dict) and item.get("name") == "contingency"), None)
    if contingency:
        base_min = minimum - float(contingency.get("min") or 0)
        required_min = base_min * float(policy.get("minimum_contingency_ratio", 0.1))
        if float(contingency.get("min") or 0) + 0.01 < required_min:
            findings.append(finding("BUDGET_CONTINGENCY_LOW", "warning", "Contingency is below policy ratio", "$.budget.categories", {"required_min": round(required_min, 2)}))
    return findings, {"budget_min": minimum, "budget_max": maximum, "budget_categories": len(categories)}


def _check_return(plan, policy):
    findings = []
    return_plan = (plan.get("audit_context") or {}).get("return_plan")
    if not return_plan:
        findings.append(finding("RETURN_DETAILS_MISSING", "warning", "No concrete return plan was provided", "$.audit_context.return_plan"))
        return findings, {"return_buffer_minutes": None}
    departure = time_to_minutes(return_plan.get("departure_time"))
    activity_end = time_to_minutes(return_plan.get("final_activity_end"))
    if departure is None or activity_end is None:
        return findings, {"return_buffer_minutes": None}
    if departure < activity_end:
        departure += 1440
    remaining = departure - activity_end - int(return_plan.get("final_leg_minutes") or 0) - int(return_plan.get("luggage_pickup_minutes") or 0)
    kind = return_plan.get("transport_kind", "other")
    policy_minimum = (policy.get("minimum_return_buffer_minutes") or {}).get(kind, (policy.get("minimum_return_buffer_minutes") or {}).get("default", 90))
    required = max(int(return_plan.get("required_buffer_minutes") or 0), int(policy_minimum))
    if remaining < required:
        findings.append(finding("RETURN_BUFFER_LOW", "error", "Return buffer is below the required minimum", "$.audit_context.return_plan", {"actual_minutes": remaining, "required_minutes": required}))
    last_day = (plan.get("itinerary") or [])[-1] if plan.get("itinerary") else {}
    stop_ids = {stop.get("id") for stop in last_day.get("stops") or [] if isinstance(stop, dict)}
    if return_plan.get("hub_id") not in stop_ids:
        findings.append(finding("RETURN_HUB_NOT_IN_ROUTE", "error", "Last-day route does not include the departure hub", "$.audit_context.return_plan.hub_id"))
    return findings, {"return_buffer_minutes": remaining, "required_return_buffer_minutes": required}


def _check_supporting_sections(plan, evidence_index, attraction_index, backup_index):
    findings = []
    for position, backup in enumerate(plan.get("backups") or []):
        if not isinstance(backup, dict):
            continue
        for attraction_id in backup.get("replacement_for") or []:
            attraction = attraction_index.get(attraction_id)
            if attraction and attraction.get("zone") != backup.get("zone"):
                findings.append(finding("BACKUP_ZONE_MISMATCH", "warning", "Backup is outside the replaced attraction's zone", "$.backups[%d].zone" % position))
    for position, item in enumerate(plan.get("emergency") or []):
        if not isinstance(item, dict):
            continue
        for evidence_id in item.get("evidence_ids") or []:
            if evidence_id not in evidence_index:
                findings.append(finding("EMERGENCY_EVIDENCE_NOT_FOUND", "error", "Emergency information references missing evidence", "$.emergency[%d].evidence_ids" % position))
    if not plan.get("lodging_recommendations"):
        findings.append(finding("LODGING_RECOMMENDATION_MISSING", "error", "At least one lodging area recommendation is required", "$.lodging_recommendations"))
    party_types = set(((plan.get("trip") or {}).get("party") or {}).get("types") or [])
    if party_types & {"elderly", "老人", "child", "children", "儿童"} and (plan.get("trip") or {}).get("intensity") == "commando":
        findings.append(finding("PARTY_INTENSITY_RISK", "error", "Commando intensity is unsafe as a default for elderly or child travelers", "$.trip.intensity"))
    return findings


def check_plan(plan, policy):
    findings = []
    attractions = plan.get("attractions") if isinstance(plan.get("attractions"), list) else []
    evidence = plan.get("evidence") if isinstance(plan.get("evidence"), list) else []
    backups = plan.get("backups") if isinstance(plan.get("backups"), list) else []
    attraction_index, attraction_duplicates = unique_index(attractions)
    evidence_index, _ = unique_index(evidence)
    backup_index, backup_duplicates = unique_index(backups)
    for duplicate, position in attraction_duplicates:
        findings.append(finding("PLAN_DUPLICATE_ATTRACTION_ID", "error", "Duplicate attraction id: %s" % duplicate, "$.attractions[%d].id" % position))
    for duplicate, position in backup_duplicates:
        findings.append(finding("PLAN_DUPLICATE_BACKUP_ID", "error", "Duplicate backup id: %s" % duplicate, "$.backups[%d].id" % position))

    findings.extend(_check_constraints(plan, attraction_index))
    weather_by_date = {item.get("date"): item for item in plan.get("weather") or [] if isinstance(item, dict)}
    day_metrics = []
    itinerary = plan.get("itinerary") if isinstance(plan.get("itinerary"), list) else []
    for day_position, day in enumerate(itinerary):
        if isinstance(day, dict):
            day_findings, metrics = _check_day(plan, day, day_position, attraction_index, backup_index, weather_by_date, policy)
            findings.extend(day_findings)
            day_metrics.append(metrics)
    trip = plan.get("trip") or {}
    if len(itinerary) != trip.get("days"):
        findings.append(finding("PLAN_DAY_COUNT_MISMATCH", "error", "Itinerary day count does not match trip.days", "$.itinerary"))
    start_date = parse_date(trip.get("start_date"))
    generated = parse_datetime(plan.get("generated_at"))
    if start_date and generated:
        days_ahead = (start_date - generated.date()).days
        if 0 <= days_ahead <= 16:
            missing_weather = [day.get("date") for day in itinerary if isinstance(day, dict) and day.get("date") not in weather_by_date]
            if missing_weather:
                findings.append(finding("WEATHER_MISSING", "warning", "Trip is in forecast range but daily weather is missing", "$.weather", {"dates": missing_weather}))

    budget_findings, budget_metrics = _check_budget(plan, policy)
    return_findings, return_metrics = _check_return(plan, policy)
    findings.extend(budget_findings)
    findings.extend(return_findings)
    findings.extend(_check_supporting_sections(plan, evidence_index, attraction_index, backup_index))
    metrics = {
        "days": len(itinerary),
        "scheduled_attractions": sum(1 for day in itinerary if isinstance(day, dict) for stop in day.get("stops") or [] if isinstance(stop, dict) and stop.get("kind") == "attraction"),
        "total_visit_minutes": sum(item["visit_minutes"] for item in day_metrics),
        "total_travel_minutes": sum(item["travel_minutes"] for item in day_metrics),
        "total_zone_transitions": sum(item["zone_transitions"] for item in day_metrics),
        "estimated_legs": sum(item["estimated_legs"] for item in day_metrics),
        "route_legs": sum(item["legs"] for item in day_metrics),
    }
    metrics.update(budget_metrics)
    metrics.update(return_metrics)
    return findings, metrics
