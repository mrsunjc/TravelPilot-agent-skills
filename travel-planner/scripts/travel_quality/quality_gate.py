"""Orchestrate schema, evidence, and plan checks into one report."""

from collections import defaultdict

from .common import find_sensitive_path, finding, utc_now_text
from .evidence_checks import check_evidence
from .plan_checks import check_plan
from .schema_validator import validate as validate_schema


def _category(code):
    prefix = code.split("_", 1)[0].lower()
    mapping = {
        "schema": "schema",
        "security": "security",
        "evidence": "evidence",
        "constraint": "constraints",
        "schedule": "schedule",
        "reservation": "schedule",
        "route": "route",
        "intensity": "intensity",
        "weather": "weather",
        "budget": "budget",
        "return": "return",
        "backup": "backups",
        "emergency": "emergency",
        "lodging": "lodging",
        "party": "personalization",
        "plan": "schema",
    }
    return mapping.get(prefix, "other")


def validate_final_plan(plan, schema, policy, strict=False):
    findings = []
    for error in validate_schema(plan, schema):
        findings.append(finding("SCHEMA_INVALID", "error", error["message"], error["path"]))

    sensitive_path = find_sensitive_path(plan)
    if sensitive_path:
        findings.append(
            finding("SECURITY_SENSITIVE_FIELD", "error", "Plan contains a blocked sensitive field", sensitive_path)
        )

    if isinstance(plan, dict):
        evidence_findings, evidence_metrics = check_evidence(plan, policy)
        plan_findings, plan_metrics = check_plan(plan, policy)
        findings.extend(evidence_findings)
        findings.extend(plan_findings)
    else:
        evidence_metrics = {}
        plan_metrics = {}

    severity_order = {"error": 0, "warning": 1, "info": 2}
    findings.sort(key=lambda item: (severity_order.get(item["severity"], 9), item["code"], item["path"]))
    errors = sum(1 for item in findings if item["severity"] == "error")
    warnings = sum(1 for item in findings if item["severity"] == "warning")
    score = max(0, 100 - errors * 12 - warnings * 3)
    minimum_score = int(policy.get("minimum_passing_score", 80))
    passed = errors == 0 and score >= minimum_score and (not strict or warnings == 0)

    category_counts = defaultdict(lambda: {"errors": 0, "warnings": 0, "info": 0})
    for item in findings:
        bucket = category_counts[_category(item["code"])]
        key = "errors" if item["severity"] == "error" else "warnings" if item["severity"] == "warning" else "info"
        bucket[key] += 1

    metrics = {}
    metrics.update(evidence_metrics)
    metrics.update(plan_metrics)
    return {
        "report_schema_version": "1.0",
        "skill_version": policy.get("skill_version"),
        "generated_at": utc_now_text(),
        "plan_id": plan.get("plan_id") if isinstance(plan, dict) else None,
        "destination": plan.get("destination") if isinstance(plan, dict) else None,
        "passed": passed,
        "strict": bool(strict),
        "score": score,
        "minimum_passing_score": minimum_score,
        "summary": {"errors": errors, "warnings": warnings, "info": len(findings) - errors - warnings},
        "categories": dict(category_counts),
        "metrics": metrics,
        "findings": findings,
    }

