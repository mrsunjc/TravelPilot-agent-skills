#!/usr/bin/env python3
"""Run the complete deterministic quality gate on a structured travel plan."""

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from travel_quality.common import load_json, write_json
from travel_quality.quality_gate import validate_final_plan


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", help="Final-plan JSON using schemas/final-plan.schema.json")
    parser.add_argument("--schema", default=str(SCRIPT_DIR.parent / "schemas" / "final-plan.schema.json"))
    parser.add_argument("--policy", default=str(SCRIPT_DIR.parent / "schemas" / "quality-policy.json"))
    parser.add_argument("--output", "-o")
    parser.add_argument("--strict", action="store_true", help="Treat any warning as a failed gate")
    args = parser.parse_args(argv)
    try:
        plan = load_json(args.plan)
        schema = load_json(args.schema)
        policy = load_json(args.policy)
        report = validate_final_plan(plan, schema, policy, strict=args.strict)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print("Quality gate input error: %s" % exc, file=sys.stderr)
        return 2
    if args.output:
        write_json(args.output, report)
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())

