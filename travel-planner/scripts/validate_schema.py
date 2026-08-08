#!/usr/bin/env python3
"""Validate a JSON document against the skill's dependency-free schema subset."""

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from travel_quality.common import load_json
from travel_quality.schema_validator import validate


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("document")
    parser.add_argument("--schema", required=True)
    args = parser.parse_args(argv)
    try:
        document = load_json(args.document)
        schema = load_json(args.schema)
        errors = validate(document, schema)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print("Validation input error: %s" % exc, file=sys.stderr)
        return 2
    report = {"passed": not errors, "errors": errors}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())

