#!/usr/bin/env python3
"""Build a deterministic, geography-first travel route skeleton.

The script deliberately avoids network and vendor SDK dependencies. Agents can
feed it verified point-to-point travel data; otherwise it falls back to clearly
labelled coordinate or zone estimates.
"""

import argparse
import itertools
import json
import math
import sys
from pathlib import Path


INTENSITY_ALIASES = {
    "light": "light",
    "relaxed": "light",
    "轻松": "light",
    "轻松游": "light",
    "normal": "normal",
    "standard": "normal",
    "正常": "normal",
    "正常游": "normal",
    "commando": "commando",
    "intense": "commando",
    "特种兵": "commando",
    "特种兵游": "commando",
}

LIMITS = {
    "light": {"visit_minutes": 300, "travel_minutes": 90, "stops": 3},
    "normal": {"visit_minutes": 420, "travel_minutes": 120, "stops": 5},
    "commando": {"visit_minutes": 540, "travel_minutes": 180, "stops": 7},
}

PRIORITY_ALIASES = {
    "must": "must",
    "必去": "must",
    "recommended": "recommended",
    "recommend": "recommended",
    "推荐": "recommended",
    "optional": "optional",
    "可选": "optional",
}

PRIORITY_WEIGHT = {"must": 100, "recommended": 60, "optional": 25}

TIME_ALIASES = {
    "morning": "morning",
    "上午": "morning",
    "afternoon": "afternoon",
    "下午": "afternoon",
    "evening": "evening",
    "night": "evening",
    "晚上": "evening",
    "夜间": "evening",
    "any": "any",
    "任意": "any",
}


class InputError(ValueError):
    """Raised when an optimizer input cannot be interpreted safely."""


def _as_number(value, field, allow_none=True):
    if value is None and allow_none:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InputError("%s must be a number" % field)
    return float(value)


def _normalize_point(raw, fallback_id=None):
    if not isinstance(raw, dict):
        raise InputError("Every point must be a JSON object")
    point_id = str(raw.get("id") or fallback_id or "").strip()
    name = str(raw.get("name") or point_id).strip()
    if not point_id:
        raise InputError("Every point needs a non-empty id")
    if not name:
        raise InputError("Every point needs a non-empty name")
    lat = _as_number(raw.get("lat"), "%s.lat" % point_id)
    lon = _as_number(raw.get("lon"), "%s.lon" % point_id)
    if (lat is None) != (lon is None):
        raise InputError("%s must provide both lat and lon, or neither" % point_id)
    if lat is not None and not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise InputError("%s has invalid coordinates" % point_id)
    return {
        "id": point_id,
        "name": name,
        "lat": lat,
        "lon": lon,
        "zone": str(raw.get("zone") or "").strip(),
    }


def _normalize_attraction(raw):
    point = _normalize_point(raw)
    priority_raw = str(raw.get("priority") or "recommended").strip().lower()
    priority = PRIORITY_ALIASES.get(priority_raw)
    if not priority:
        raise InputError("%s has unsupported priority: %s" % (point["id"], priority_raw))
    time_raw = str(raw.get("time_preference") or "any").strip().lower()
    time_preference = TIME_ALIASES.get(time_raw)
    if not time_preference:
        raise InputError(
            "%s has unsupported time_preference: %s" % (point["id"], time_raw)
        )
    duration = raw.get("duration_minutes", 120)
    if isinstance(duration, bool) or not isinstance(duration, (int, float)) or duration <= 0:
        raise InputError("%s.duration_minutes must be positive" % point["id"])
    available_days = raw.get("available_days")
    if available_days is not None:
        if not isinstance(available_days, list) or not all(
            isinstance(day, int) and not isinstance(day, bool) and day >= 1
            for day in available_days
        ):
            raise InputError("%s.available_days must contain positive integers" % point["id"])
        available_days = sorted(set(available_days))
    point.update(
        {
            "priority": priority,
            "duration_minutes": int(round(duration)),
            "time_preference": "evening" if raw.get("night") else time_preference,
            "night": bool(raw.get("night", False)),
            "mandatory": bool(raw.get("mandatory", False)) or priority == "must",
            "excluded": bool(raw.get("excluded", False)),
            "closed": bool(raw.get("closed", False)),
            "available_days": available_days,
        }
    )
    return point


def _haversine_km(a, b):
    if a.get("lat") is None or b.get("lat") is None:
        return None
    earth_radius_km = 6371.0088
    lat1, lon1 = math.radians(a["lat"]), math.radians(a["lon"])
    lat2, lon2 = math.radians(b["lat"]), math.radians(b["lon"])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    )
    return earth_radius_km * 2 * math.asin(min(1.0, math.sqrt(h)))


class TravelEstimator:
    def __init__(self, travel_times, party_size=1):
        self.party_size = max(1, int(party_size or 1))
        self.records = {}
        if travel_times is None:
            travel_times = []
        if not isinstance(travel_times, list):
            raise InputError("travel_times must be a list")
        for index, raw in enumerate(travel_times):
            if not isinstance(raw, dict):
                raise InputError("travel_times[%d] must be an object" % index)
            source_id = str(raw.get("from") or "").strip()
            target_id = str(raw.get("to") or "").strip()
            if not source_id or not target_id:
                raise InputError("Every travel_times record needs from and to")
            minutes = raw.get("minutes")
            if isinstance(minutes, bool) or not isinstance(minutes, (int, float)) or minutes < 0:
                raise InputError("Travel time %s -> %s needs non-negative minutes" % (source_id, target_id))
            distance = _as_number(
                raw.get("distance_km"),
                "travel_times[%d].distance_km" % index,
            )
            cost = _as_number(raw.get("cost"), "travel_times[%d].cost" % index)
            record = {
                "minutes": int(math.ceil(minutes)),
                "distance_km": round(distance, 2) if distance is not None else None,
                "mode": str(raw.get("mode") or "unspecified"),
                "cost": round(cost, 2) if cost is not None else None,
                "source": str(raw.get("source") or "provided_travel_time"),
                "verified": bool(raw.get("verified", True)),
                "bidirectional": bool(raw.get("bidirectional", True)),
            }
            self.records[(source_id, target_id)] = record

    def leg(self, a, b):
        if a["id"] == b["id"]:
            return self._format_leg(a, b, 0, 0.0, "none", 0.0, "same_point", True)

        direct = self.records.get((a["id"], b["id"]))
        if direct:
            return self._from_record(a, b, direct)

        reverse = self.records.get((b["id"], a["id"]))
        if reverse and reverse.get("bidirectional"):
            copied = dict(reverse)
            copied["source"] = "%s (reverse assumed)" % reverse["source"]
            copied["verified"] = False
            return self._from_record(a, b, copied)

        direct_km = _haversine_km(a, b)
        if direct_km is not None:
            route_km = max(0.1, direct_km * 1.25)
            if route_km <= 1.5:
                mode = "walk"
                minutes = math.ceil(route_km / 4.5 * 60 + 3)
            elif route_km <= 12:
                if self.party_size >= 3 and route_km >= 3:
                    mode = "taxi_or_ride_hail"
                    minutes = math.ceil(route_km / 28 * 60 + 8)
                else:
                    mode = "public_transit"
                    minutes = math.ceil(route_km / 20 * 60 + 12)
            elif route_km <= 50:
                mode = "taxi_or_express_transit"
                minutes = math.ceil(route_km / 32 * 60 + 12)
            else:
                mode = "regional_transit"
                minutes = math.ceil(route_km / 50 * 60 + 20)
            return self._format_leg(
                a,
                b,
                minutes,
                route_km,
                mode,
                None,
                "coordinate_estimate",
                False,
            )

        if a.get("zone") and a.get("zone") == b.get("zone"):
            minutes = 15
        elif a.get("zone") and b.get("zone"):
            minutes = 45
        else:
            minutes = 30
        return self._format_leg(
            a,
            b,
            minutes,
            None,
            "transit_or_taxi_to_verify",
            None,
            "zone_heuristic",
            False,
        )

    def _from_record(self, a, b, record):
        return self._format_leg(
            a,
            b,
            record["minutes"],
            record["distance_km"],
            record["mode"],
            record["cost"],
            record["source"],
            record["verified"],
        )

    @staticmethod
    def _format_leg(a, b, minutes, distance, mode, cost, source, verified):
        return {
            "from": a["id"],
            "from_name": a["name"],
            "to": b["id"],
            "to_name": b["name"],
            "minutes": int(minutes),
            "distance_km": round(distance, 2) if distance is not None else None,
            "mode": mode,
            "cost": cost,
            "source": source,
            "verified": bool(verified),
        }


def _normalize_input(data):
    if not isinstance(data, dict):
        raise InputError("Input root must be a JSON object")
    destination = str(data.get("destination") or "").strip()
    if not destination:
        raise InputError("destination is required")
    days = data.get("days")
    if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 30:
        raise InputError("days must be an integer between 1 and 30")
    intensity_raw = str(data.get("intensity") or "normal").strip().lower()
    intensity = INTENSITY_ALIASES.get(intensity_raw)
    if not intensity:
        raise InputError("Unsupported intensity: %s" % intensity_raw)
    attractions_raw = data.get("attractions")
    if not isinstance(attractions_raw, list) or not attractions_raw:
        raise InputError("attractions must be a non-empty list")
    attractions = [_normalize_attraction(item) for item in attractions_raw]
    ids = [item["id"] for item in attractions]
    if len(ids) != len(set(ids)):
        raise InputError("Attraction ids must be unique")

    anchors = {}
    for field in ("lodging", "arrival_anchor", "departure_anchor"):
        if data.get(field) is not None:
            anchors[field] = _normalize_point(data[field], field)

    party_raw = data.get("party") or {}
    if not isinstance(party_raw, dict):
        raise InputError("party must be an object")
    party_size = party_raw.get("size", 1)
    if isinstance(party_size, bool) or not isinstance(party_size, int) or party_size < 1:
        raise InputError("party.size must be a positive integer")

    return {
        "destination": destination,
        "days": days,
        "intensity": intensity,
        "party_size": party_size,
        "attractions": attractions,
        "travel_times": data.get("travel_times") or [],
        "anchors": anchors,
    }


def _availability(item, day_number):
    allowed = item.get("available_days")
    return allowed is None or day_number in allowed


def _assignment_score(item, day, estimator, limits):
    items = day["items"]
    projected_minutes = day["visit_minutes"] + item["duration_minutes"]
    overflow = max(0, projected_minutes - limits["visit_minutes"])
    stop_overflow = max(0, len(items) + 1 - limits["stops"])
    load_penalty = day["visit_minutes"] / max(1, limits["visit_minutes"]) * 25
    if not items:
        geographic_cost = 35
    else:
        geographic_cost = min(estimator.leg(existing, item)["minutes"] for existing in items)
        zones = {existing.get("zone") for existing in items if existing.get("zone")}
        if item.get("zone") and item["zone"] in zones:
            geographic_cost -= 20
        elif item.get("zone") and zones:
            geographic_cost += 70
    return (
        geographic_cost
        + load_penalty
        + overflow * 20
        + stop_overflow * 500
        + day["day"] * 0.001
    )


def _assign_days(attractions, days_count, limits, estimator):
    day_states = [
        {"day": day, "items": [], "visit_minutes": 0}
        for day in range(1, days_count + 1)
    ]
    unscheduled = []
    eligible = []
    for item in attractions:
        if item["excluded"]:
            unscheduled.append(_unscheduled_item(item, "user_excluded"))
        elif item["closed"]:
            unscheduled.append(_unscheduled_item(item, "closed"))
        else:
            eligible.append(item)

    mandatory_items = sorted(
        (item for item in eligible if item["mandatory"]),
        key=lambda item: (-item["duration_minutes"], item["id"]),
    )

    def place_item(item):
        candidates = [day for day in day_states if _availability(item, day["day"])]
        if not candidates:
            unscheduled.append(_unscheduled_item(item, "not_available_on_trip_days"))
            return
        feasible = [
            day
            for day in candidates
            if day["visit_minutes"] + item["duration_minutes"] <= limits["visit_minutes"]
            and len(day["items"]) < limits["stops"]
        ]
        if feasible:
            pool = feasible
        elif item["mandatory"]:
            pool = candidates
        else:
            unscheduled.append(_unscheduled_item(item, "capacity_or_intensity_limit"))
            return
        selected = min(pool, key=lambda day: _assignment_score(item, day, estimator, limits))
        selected["items"].append(item)
        selected["visit_minutes"] += item["duration_minutes"]

    for item in mandatory_items:
        place_item(item)

    seeded_zones = {
        item["zone"]
        for day in day_states
        for item in day["items"]
        if item.get("zone")
    }
    remaining_items = sorted(
        (item for item in eligible if not item["mandatory"]),
        key=lambda item: (
            -PRIORITY_WEIGHT[item["priority"]],
            0 if item.get("zone") in seeded_zones else 1,
            -item["duration_minutes"],
            item["id"],
        ),
    )
    for item in remaining_items:
        place_item(item)
    return day_states, unscheduled


def _unscheduled_item(item, reason):
    return {
        "id": item["id"],
        "name": item["name"],
        "priority": item["priority"],
        "mandatory": item["mandatory"],
        "reason": reason,
    }


def _route_score(order, estimator, start=None, end=None):
    if not order:
        return 0
    points = []
    if start:
        points.append(start)
    points.extend(order)
    if end:
        points.append(end)
    travel = sum(estimator.leg(a, b)["minutes"] for a, b in zip(points, points[1:]))
    zone_transitions = sum(
        1
        for a, b in zip(order, order[1:])
        if a.get("zone") and b.get("zone") and a["zone"] != b["zone"]
    )
    preference_penalty = 0.0
    denominator = max(1, len(order) - 1)
    for index, item in enumerate(order):
        fraction = index / denominator
        if item["time_preference"] == "morning":
            preference_penalty += max(0.0, fraction - 0.4) * 120
        elif item["time_preference"] == "evening":
            preference_penalty += max(0.0, 0.6 - fraction) * 160
        if item["night"] and index != len(order) - 1:
            preference_penalty += 45 * (len(order) - 1 - index)
    return travel + zone_transitions * 25 + preference_penalty


def _nearest_neighbor(items, estimator, start=None):
    remaining = sorted(items, key=lambda item: item["id"])
    order = []
    current = start
    while remaining:
        if current is None:
            chosen = remaining[0]
        else:
            chosen = min(
                remaining,
                key=lambda item: (estimator.leg(current, item)["minutes"], item["id"]),
            )
        order.append(chosen)
        remaining.remove(chosen)
        current = chosen
    return order


def _order_day(items, estimator, start=None, end=None):
    if len(items) <= 1:
        return list(items)
    sorted_items = sorted(items, key=lambda item: item["id"])
    if len(sorted_items) <= 8:
        return list(
            min(
                itertools.permutations(sorted_items),
                key=lambda order: (_route_score(order, estimator, start, end), tuple(i["id"] for i in order)),
            )
        )
    morning = [item for item in sorted_items if item["time_preference"] == "morning"]
    flexible = [item for item in sorted_items if item["time_preference"] in ("any", "afternoon")]
    evening = [item for item in sorted_items if item["time_preference"] == "evening"]
    order = []
    current = start
    for group in (morning, flexible, evening):
        segment = _nearest_neighbor(group, estimator, current)
        order.extend(segment)
        if segment:
            current = segment[-1]
    return order


def _period_for(index, total, item):
    if item["night"] or item["time_preference"] == "evening":
        return "evening"
    if item["time_preference"] == "morning":
        return "morning"
    if total <= 2:
        return "morning" if index == 0 else "afternoon"
    fraction = index / max(1, total - 1)
    if fraction < 0.34:
        return "morning"
    if fraction < 0.75:
        return "afternoon"
    return "evening"


def _build_day_output(day_state, days_count, anchors, estimator):
    day_number = day_state["day"]
    start = anchors.get("arrival_anchor") if day_number == 1 else anchors.get("lodging")
    if start is None:
        start = anchors.get("lodging")
    if day_number == days_count:
        end = anchors.get("departure_anchor") or anchors.get("lodging")
    else:
        end = anchors.get("lodging")
    ordered = _order_day(day_state["items"], estimator, start, end)

    stops = []
    for index, item in enumerate(ordered):
        stops.append(
            {
                "sequence": index + 1,
                "id": item["id"],
                "name": item["name"],
                "zone": item["zone"] or None,
                "priority": item["priority"],
                "duration_minutes": item["duration_minutes"],
                "suggested_period": _period_for(index, len(ordered), item),
                "mandatory": item["mandatory"],
            }
        )

    route_points = []
    if start and ordered:
        route_points.append(start)
    route_points.extend(ordered)
    if end and ordered:
        route_points.append(end)
    legs = [estimator.leg(a, b) for a, b in zip(route_points, route_points[1:])]
    zones = []
    for item in ordered:
        if item.get("zone") and item["zone"] not in zones:
            zones.append(item["zone"])
    zone_transitions = sum(
        1
        for a, b in zip(ordered, ordered[1:])
        if a.get("zone") and b.get("zone") and a["zone"] != b["zone"]
    )
    return {
        "day": day_number,
        "zone_focus": zones,
        "stops": stops,
        "legs": legs,
        "visit_minutes": sum(item["duration_minutes"] for item in ordered),
        "travel_minutes": sum(leg["minutes"] for leg in legs),
        "zone_transitions": zone_transitions,
    }


def _audit(normalized, day_outputs, unscheduled):
    limits = LIMITS[normalized["intensity"]]
    errors = []
    warnings = []
    scheduled_ids = {
        stop["id"] for day in day_outputs for stop in day["stops"]
    }
    required = {
        item["id"]
        for item in normalized["attractions"]
        if item["mandatory"] and not item["excluded"]
    }
    missing_required = sorted(required - scheduled_ids)
    if missing_required:
        errors.append("Mandatory attractions were not scheduled: %s" % ", ".join(missing_required))

    for day in day_outputs:
        if day["visit_minutes"] > limits["visit_minutes"]:
            warnings.append(
                "Day %d visit time exceeds the %s intensity limit" % (day["day"], normalized["intensity"])
            )
        if day["travel_minutes"] > limits["travel_minutes"]:
            warnings.append(
                "Day %d travel time exceeds the %s intensity guideline" % (day["day"], normalized["intensity"])
            )
        if len(day["stops"]) > limits["stops"]:
            warnings.append(
                "Day %d has more stops than the %s intensity guideline" % (day["day"], normalized["intensity"])
            )
        if day["zone_transitions"] > 1:
            warnings.append("Day %d changes zones more than once" % day["day"])

    all_legs = [leg for day in day_outputs for leg in day["legs"]]
    estimated_legs = [leg for leg in all_legs if not leg["verified"]]
    if estimated_legs:
        warnings.append(
            "%d of %d route legs are estimates and need map verification"
            % (len(estimated_legs), len(all_legs))
        )
    optional_unscheduled = [item for item in unscheduled if not item["mandatory"] and item["reason"] != "user_excluded"]
    if optional_unscheduled:
        warnings.append(
            "%d non-mandatory attractions were left out by availability or intensity limits"
            % len(optional_unscheduled)
        )

    metrics = {
        "scheduled_attractions": len(scheduled_ids),
        "unscheduled_attractions": len(unscheduled),
        "total_visit_minutes": sum(day["visit_minutes"] for day in day_outputs),
        "total_travel_minutes": sum(day["travel_minutes"] for day in day_outputs),
        "zone_transitions": sum(day["zone_transitions"] for day in day_outputs),
        "verified_legs": len(all_legs) - len(estimated_legs),
        "estimated_legs": len(estimated_legs),
    }
    return {"passed": not errors, "errors": errors, "warnings": warnings, "metrics": metrics}


def optimize_trip(data):
    normalized = _normalize_input(data)
    limits = LIMITS[normalized["intensity"]]
    estimator = TravelEstimator(normalized["travel_times"], normalized["party_size"])
    day_states, unscheduled = _assign_days(
        normalized["attractions"], normalized["days"], limits, estimator
    )
    day_outputs = [
        _build_day_output(day, normalized["days"], normalized["anchors"], estimator)
        for day in day_states
    ]
    audit = _audit(normalized, day_outputs, unscheduled)
    all_legs = [leg for day in day_outputs for leg in day["legs"]]
    quality = {
        "method": "provided_travel_times" if normalized["travel_times"] else "coordinate_or_zone_estimate",
        "verified_legs": sum(1 for leg in all_legs if leg["verified"]),
        "estimated_legs": sum(1 for leg in all_legs if not leg["verified"]),
        "note": (
            "Use live map routes before publishing exact distances, times, or costs."
            if any(not leg["verified"] for leg in all_legs)
            else "All emitted legs use provided route data."
        ),
    }
    return {
        "schema_version": "1.0",
        "destination": normalized["destination"],
        "days_count": normalized["days"],
        "intensity": normalized["intensity"],
        "limits": limits,
        "days": day_outputs,
        "unscheduled": unscheduled,
        "data_quality": quality,
        "audit": audit,
    }


def _read_json(path):
    try:
        with Path(path).open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise InputError("Cannot read input JSON: %s" % exc)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="UTF-8 trip input JSON")
    parser.add_argument("--output", "-o", help="Write result JSON to this path")
    args = parser.parse_args(argv)
    try:
        result = optimize_trip(_read_json(args.input))
    except InputError as exc:
        print("Input error: %s" % exc, file=sys.stderr)
        return 2
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    sys.exit(main())
