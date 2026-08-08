#!/usr/bin/env python3
"""Run deterministic travel quality evaluations from a JSON suite."""

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
QUALITY_ROOT = REPO_ROOT / "travel-planner" / "scripts"
if str(QUALITY_ROOT) not in sys.path:
    sys.path.insert(0, str(QUALITY_ROOT))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from eval_fixture import mutate, valid_plan
from travel_quality.common import load_json
from travel_quality.quality_gate import validate_final_plan


def run_suite(path):
    suite = load_json(path)
    schema = load_json(REPO_ROOT / "travel-planner" / "schemas" / "final-plan.schema.json")
    policy = load_json(REPO_ROOT / "travel-planner" / "schemas" / "quality-policy.json")
    results = []
    for case in suite.get("cases") or []:
        plan = mutate(valid_plan(), case.get("mutation", "valid"))
        report = validate_final_plan(plan, schema, policy)
        codes = sorted({item["code"] for item in report["findings"]})
        expected_codes = sorted(case.get("expected_codes") or [])
        expected_passed = bool(case.get("expected_passed"))
        missing = sorted(set(expected_codes) - set(codes))
        expectation_met = report["passed"] == expected_passed and not missing
        results.append({"id": case["id"], "expectation_met": expectation_met, "expected_passed": expected_passed, "actual_passed": report["passed"], "score": report["score"], "missing_expected_codes": missing, "actual_codes": codes})
    passed = all(item["expectation_met"] for item in results)
    return {"report_schema_version": "1.0", "suite_id": suite.get("suite_id"), "suite_version": suite.get("suite_version"), "skill_version": policy.get("skill_version"), "passed": passed, "metrics": {"cases": len(results), "expectation_pass_rate": (sum(1 for item in results if item["expectation_met"]) / len(results)) if results else 0}, "results": results}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("suite")
    parser.add_argument("--output", "-o")
    args = parser.parse_args(argv)
    try:
        report = run_suite(args.suite)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print("Evaluation error: %s" % exc, file=sys.stderr)
        return 2
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
