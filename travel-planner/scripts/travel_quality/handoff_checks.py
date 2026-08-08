"""Validate integrity and continuity across agent/model handoff documents."""

from .common import document_digest, find_sensitive_path, finding, parse_datetime
from .schema_validator import validate as validate_schema


def validate_handoff_chain(documents, schema):
    findings = []
    by_id = {}
    positions = {}
    for position, document in enumerate(documents):
        path = "$[%d]" % position
        for error in validate_schema(document, schema):
            findings.append(finding("HANDOFF_SCHEMA_INVALID", "error", error["message"], path + error["path"][1:]))
        sensitive = find_sensitive_path(document, path)
        if sensitive:
            findings.append(finding("HANDOFF_SENSITIVE_FIELD", "error", "Handoff contains a blocked sensitive field", sensitive))
        handoff_id = document.get("handoff_id") if isinstance(document, dict) else None
        if handoff_id in by_id:
            findings.append(finding("HANDOFF_DUPLICATE_ID", "error", "Duplicate handoff id: %s" % handoff_id, path + ".handoff_id"))
        else:
            by_id[handoff_id] = document
            positions[handoff_id] = position
        expected_digest = document_digest(document, {"content_digest"}) if isinstance(document, dict) else None
        if expected_digest and document.get("content_digest") != expected_digest:
            findings.append(finding("HANDOFF_DIGEST_MISMATCH", "error", "Handoff content changed after its digest was created", path + ".content_digest", {"expected": expected_digest}))

    for position, document in enumerate(documents):
        if not isinstance(document, dict):
            continue
        path = "$[%d]" % position
        parent_id = document.get("parent_handoff_id")
        if not parent_id:
            continue
        parent = by_id.get(parent_id)
        if parent is None:
            findings.append(finding("HANDOFF_PARENT_NOT_FOUND", "error", "Parent handoff is missing: %s" % parent_id, path + ".parent_handoff_id"))
            continue
        if positions.get(parent_id, position) >= position:
            findings.append(finding("HANDOFF_PARENT_ORDER", "error", "Parent handoff must appear before child", path + ".parent_handoff_id"))
        if parent.get("to_role") != document.get("from_role"):
            findings.append(finding("HANDOFF_ROLE_DISCONTINUITY", "error", "Child from_role does not match parent to_role", path + ".from_role"))
        parent_time = parse_datetime(parent.get("created_at"))
        child_time = parse_datetime(document.get("created_at"))
        if parent_time and child_time and child_time < parent_time:
            findings.append(finding("HANDOFF_TIME_REVERSED", "error", "Child handoff predates its parent", path + ".created_at"))

        parent_issues = {item.get("id") for item in parent.get("unresolved_issues") or [] if isinstance(item, dict)}
        child_issues = {item.get("id") for item in document.get("unresolved_issues") or [] if isinstance(item, dict)}
        resolved = set(document.get("resolved_issue_ids") or [])
        dropped = sorted(parent_issues - child_issues - resolved)
        if dropped:
            findings.append(finding("HANDOFF_ISSUE_DROPPED", "error", "Unresolved parent issues were silently dropped", path + ".unresolved_issues", {"issue_ids": dropped}))

        parent_evidence = set(parent.get("evidence_ids") or [])
        child_evidence = set(document.get("evidence_ids") or [])
        declared_dropped = set((document.get("payload") or {}).get("dropped_evidence_ids") or [])
        lost = sorted(parent_evidence - child_evidence - declared_dropped)
        if lost:
            findings.append(finding("HANDOFF_EVIDENCE_DROPPED", "warning", "Evidence ids disappeared without an explicit drop declaration", path + ".evidence_ids", {"evidence_ids": lost}))

    findings.sort(key=lambda item: ({"error": 0, "warning": 1, "info": 2}.get(item["severity"], 9), item["code"], item["path"]))
    errors = sum(1 for item in findings if item["severity"] == "error")
    warnings = sum(1 for item in findings if item["severity"] == "warning")
    return {
        "report_schema_version": "1.0",
        "passed": errors == 0,
        "summary": {"documents": len(documents), "errors": errors, "warnings": warnings},
        "findings": findings,
    }

