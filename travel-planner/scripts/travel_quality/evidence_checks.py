"""Evidence provenance and claim-consistency checks."""

from collections import defaultdict

from .common import canonical_json, finding, parse_datetime, unique_index, value_digest


def check_evidence(plan, policy):
    findings = []
    claims = plan.get("claims") if isinstance(plan.get("claims"), list) else []
    evidence = plan.get("evidence") if isinstance(plan.get("evidence"), list) else []
    claim_index, claim_duplicates = unique_index(claims)
    evidence_index, evidence_duplicates = unique_index(evidence)

    for duplicate, position in claim_duplicates:
        findings.append(
            finding("EVIDENCE_DUPLICATE_CLAIM_ID", "error", "Duplicate claim id: %s" % duplicate, "$.claims[%d].id" % position)
        )
    for duplicate, position in evidence_duplicates:
        findings.append(
            finding("EVIDENCE_DUPLICATE_SOURCE_ID", "error", "Duplicate evidence id: %s" % duplicate, "$.evidence[%d].id" % position)
        )

    generated_at = parse_datetime(plan.get("generated_at"))
    critical = set(policy.get("critical_claim_types") or [])
    allowed_by_type = policy.get("allowed_source_types_by_claim") or {}
    max_ages = policy.get("max_evidence_age_days") or {}

    support_index = defaultdict(list)
    for evidence_position, source in enumerate(evidence):
        if not isinstance(source, dict):
            continue
        accessed = parse_datetime(source.get("accessed_at"))
        if generated_at and accessed and accessed > generated_at:
            findings.append(
                finding(
                    "EVIDENCE_ACCESSED_IN_FUTURE",
                    "error",
                    "Evidence access time is later than plan generation time",
                    "$.evidence[%d].accessed_at" % evidence_position,
                )
            )
        for support_position, support in enumerate(source.get("supports") or []):
            if not isinstance(support, dict):
                continue
            claim_id = support.get("claim_id")
            if claim_id not in claim_index:
                findings.append(
                    finding(
                        "EVIDENCE_UNKNOWN_CLAIM",
                        "error",
                        "Evidence references an unknown claim: %s" % claim_id,
                        "$.evidence[%d].supports[%d].claim_id" % (evidence_position, support_position),
                    )
                )
            support_index[claim_id].append((source, support, evidence_position))

    verified_claims = 0
    verified_critical = 0
    for position, claim in enumerate(claims):
        if not isinstance(claim, dict):
            continue
        claim_id = claim.get("id")
        claim_type = claim.get("type", "other")
        status = claim.get("status")
        path = "$.claims[%d]" % position
        evidence_ids = claim.get("evidence_ids") or []

        if claim_type in critical and not claim.get("as_of"):
            findings.append(
                finding("EVIDENCE_AS_OF_REQUIRED", "error", "Critical dynamic claim needs as_of", path + ".as_of")
            )
        if status == "estimated" and not claim.get("method"):
            findings.append(
                finding("EVIDENCE_ESTIMATE_METHOD_REQUIRED", "error", "Estimated claim needs a calculation or estimation method", path + ".method")
            )
        if status == "unverified" and claim_type in critical:
            findings.append(
                finding("EVIDENCE_CRITICAL_UNVERIFIED", "warning", "Critical claim is explicitly unverified", path)
            )
        if status != "verified":
            continue

        verified_claims += 1
        if claim_type in critical:
            verified_critical += 1
        if not evidence_ids:
            findings.append(
                finding("EVIDENCE_REQUIRED", "error", "Verified claim has no evidence_ids", path + ".evidence_ids")
            )
            continue

        expected_digest = value_digest(claim.get("value"))
        matching_sources = []
        for evidence_id in evidence_ids:
            source = evidence_index.get(evidence_id)
            if source is None:
                findings.append(
                    finding("EVIDENCE_SOURCE_NOT_FOUND", "error", "Claim references missing evidence: %s" % evidence_id, path + ".evidence_ids")
                )
                continue
            source_supports = [entry for entry in support_index.get(claim_id, []) if entry[0].get("id") == evidence_id]
            if not source_supports:
                findings.append(
                    finding("EVIDENCE_BACKLINK_MISSING", "error", "Evidence does not declare support for claim %s" % claim_id, path + ".evidence_ids")
                )
                continue
            matching_sources.append(source)
            if not any(entry[1].get("value_digest") == expected_digest for entry in source_supports):
                findings.append(
                    finding("EVIDENCE_VALUE_MISMATCH", "error", "Evidence digest does not match the current claim value", path + ".value")
                )

            accessed = parse_datetime(source.get("accessed_at"))
            max_age = max_ages.get(claim_type, max_ages.get("other"))
            if generated_at and accessed and max_age is not None:
                age_days = (generated_at - accessed).total_seconds() / 86400.0
                if age_days > float(max_age):
                    findings.append(
                        finding(
                            "EVIDENCE_STALE",
                            "error" if claim_type in ("closure_status", "weather") else "warning",
                            "Evidence is %.1f days old; policy maximum is %s" % (age_days, max_age),
                            path + ".evidence_ids",
                            {"claim_type": claim_type, "age_days": round(age_days, 2)},
                        )
                    )

        allowed_types = set(allowed_by_type.get(claim_type) or [])
        if allowed_types and matching_sources and not any(source.get("source_type") in allowed_types for source in matching_sources):
            findings.append(
                finding(
                    "EVIDENCE_SOURCE_AUTHORITY_LOW",
                    "error" if claim_type in critical else "warning",
                    "Claim lacks an allowed authoritative source type",
                    path + ".evidence_ids",
                    {"allowed_source_types": sorted(allowed_types)},
                )
            )

    grouped = defaultdict(set)
    for claim in claims:
        if isinstance(claim, dict) and claim.get("status") == "verified":
            grouped[(claim.get("subject_id"), claim.get("type"))].add(canonical_json(claim.get("value")))
    for (subject_id, claim_type), values in grouped.items():
        if len(values) > 1:
            findings.append(
                finding(
                    "EVIDENCE_CLAIM_CONFLICT",
                    "error",
                    "Conflicting verified claims for %s / %s" % (subject_id, claim_type),
                    "$.claims",
                )
            )

    scheduled_ids = {
        stop.get("attraction_id")
        for day in plan.get("itinerary") or []
        if isinstance(day, dict)
        for stop in day.get("stops") or []
        if isinstance(stop, dict) and stop.get("kind") == "attraction"
    }
    required_types = set(policy.get("required_claims_per_scheduled_attraction") or [])
    claims_by_subject = defaultdict(set)
    for claim in claims:
        if isinstance(claim, dict):
            claims_by_subject[claim.get("subject_id")].add(claim.get("type"))
    for attraction_id in sorted(item for item in scheduled_ids if item):
        missing = sorted(required_types - claims_by_subject.get(attraction_id, set()))
        if missing:
            findings.append(
                finding(
                    "EVIDENCE_CLAIM_COVERAGE_MISSING",
                    "error",
                    "Scheduled attraction lacks required dynamic claims: %s" % ", ".join(missing),
                    "$.claims",
                    {"attraction_id": attraction_id},
                )
            )

    metrics = {
        "claims": len(claims),
        "verified_claims": verified_claims,
        "critical_claims": sum(1 for claim in claims if isinstance(claim, dict) and claim.get("type") in critical),
        "verified_critical_claims": verified_critical,
        "evidence_sources": len(evidence),
    }
    return findings, metrics

