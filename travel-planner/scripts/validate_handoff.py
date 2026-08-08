#!/usr/bin/env python3
"""Validate one or more ordered cross-agent handoff documents."""

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from travel_quality.common import document_digest, load_json
from travel_quality.handoff_checks import validate_handoff_chain


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("documents", nargs="+")
    parser.add_argument("--schema", default=str(SCRIPT_DIR.parent / "schemas" / "handoff.schema.json"))
    parser.add_argument("--digest-only", action="store_true", help="Print the expected digest for one document")
    args = parser.parse_args(argv)
    try:
        documents = [load_json(path) for path in args.documents]
        if args.digest_only:
            if len(documents) != 1:
                parser.error("--digest-only accepts exactly one document")
            print(document_digest(documents[0], {"content_digest"}))
            return 0
        schema = load_json(args.schema)
        report = validate_handoff_chain(documents, schema)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print("Handoff validation input error: %s" % exc, file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())

