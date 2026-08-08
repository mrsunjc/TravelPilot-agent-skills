#!/usr/bin/env python3
"""Store portable travel-plan JSON and destination wishlists safely."""

import argparse
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


SENSITIVE_KEY_PATTERN = re.compile(
    r"(^|_)(api[_-]?key|access[_-]?token|refresh[_-]?token|password|passwd|secret|"
    r"authorization|cookie|session|passport|id[_-]?card|credit[_-]?card|cvv|"
    r"booking[_-]?(code|reference)|verification[_-]?code)($|_)",
    re.IGNORECASE,
)


class StoreError(ValueError):
    """Raised when persistent data would be unsafe or invalid."""


def _utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _resolve_root(raw_root):
    root = raw_root or os.environ.get("TRAVEL_PLANNER_DATA_DIR")
    if not root:
        raise StoreError(
            "Specify --root or set TRAVEL_PLANNER_DATA_DIR; no implicit data directory is used"
        )
    return Path(root).expanduser().resolve()


def _read_json(path):
    try:
        with Path(path).open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise StoreError("Cannot read JSON: %s" % exc)


def _read_json_if_exists(path, default):
    if not path.exists():
        return default
    return _read_json(path)


def _find_sensitive_path(value, path="$"):
    if isinstance(value, dict):
        for key, nested in value.items():
            key_text = str(key)
            child_path = "%s.%s" % (path, key_text)
            if SENSITIVE_KEY_PATTERN.search(key_text):
                return child_path
            found = _find_sensitive_path(nested, child_path)
            if found:
                return found
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            found = _find_sensitive_path(nested, "%s[%d]" % (path, index))
            if found:
                return found
    return None


def _atomic_write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = None
    temp_path = None
    try:
        handle = tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=str(path.parent),
            prefix=".%s." % path.name,
            suffix=".tmp",
            delete=False,
        )
        temp_path = Path(handle.name)
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
        handle.close()
        handle = None
        os.replace(str(temp_path), str(path))
    finally:
        if handle is not None:
            handle.close()
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


def _slug(text):
    cleaned = re.sub(r"[^\w\-]+", "-", text.strip(), flags=re.UNICODE).strip("-")
    return cleaned[:60] or "trip"


def save_plan(root, plan_path):
    plan = _read_json(plan_path)
    if not isinstance(plan, dict):
        raise StoreError("Plan JSON root must be an object")
    sensitive_path = _find_sensitive_path(plan)
    if sensitive_path:
        raise StoreError("Plan contains a blocked sensitive field at %s" % sensitive_path)
    destination = str(plan.get("destination") or "").strip()
    if not destination:
        raise StoreError("Plan needs a destination field")
    saved_at = _utc_now()
    compact_time = saved_at.replace("-", "").replace(":", "").replace("T", "-").replace("Z", "")
    plan_id = "%s-%s" % (compact_time, _slug(destination))
    stored = dict(plan)
    stored["storage"] = {"plan_id": plan_id, "saved_at": saved_at}
    target = root / "plans" / (plan_id + ".json")
    counter = 2
    while target.exists():
        target = root / "plans" / ("%s-%d.json" % (plan_id, counter))
        counter += 1
    _atomic_write_json(target, stored)
    return {"plan_id": target.stem, "destination": destination, "path": str(target), "saved_at": saved_at}


def list_plans(root):
    plans_dir = root / "plans"
    if not plans_dir.exists():
        return []
    results = []
    for path in sorted(plans_dir.glob("*.json"), reverse=True):
        try:
            plan = _read_json(path)
        except StoreError:
            results.append({"plan_id": path.stem, "path": str(path), "status": "unreadable"})
            continue
        results.append(
            {
                "plan_id": path.stem,
                "destination": plan.get("destination"),
                "days_count": plan.get("days_count") or plan.get("days"),
                "saved_at": (plan.get("storage") or {}).get("saved_at"),
                "path": str(path),
            }
        )
    return results


def _wishlist_path(root):
    return root / "wishlist.json"


def wishlist_list(root):
    payload = _read_json_if_exists(_wishlist_path(root), {"schema_version": "1.0", "items": []})
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise StoreError("wishlist.json has an invalid structure")
    return payload


def wishlist_add(root, destination, note=""):
    destination = destination.strip()
    if not destination:
        raise StoreError("destination cannot be empty")
    payload = wishlist_list(root)
    for item in payload["items"]:
        if str(item.get("destination", "")).casefold() == destination.casefold():
            if note:
                item["note"] = note
            item["updated_at"] = _utc_now()
            _atomic_write_json(_wishlist_path(root), payload)
            return {"action": "updated", "item": item}
    item = {"destination": destination, "note": note, "added_at": _utc_now()}
    payload["items"].append(item)
    payload["items"].sort(key=lambda entry: str(entry.get("destination", "")).casefold())
    _atomic_write_json(_wishlist_path(root), payload)
    return {"action": "added", "item": item}


def wishlist_remove(root, destination):
    payload = wishlist_list(root)
    before = len(payload["items"])
    payload["items"] = [
        item
        for item in payload["items"]
        if str(item.get("destination", "")).casefold() != destination.strip().casefold()
    ]
    if len(payload["items"]) == before:
        return {"action": "not_found", "destination": destination}
    _atomic_write_json(_wishlist_path(root), payload)
    return {"action": "removed", "destination": destination}


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", help="Data directory outside the installed skill")
    subparsers = parser.add_subparsers(dest="command", required=True)

    save_parser = subparsers.add_parser("save", help="Save a plan JSON")
    save_parser.add_argument("--plan", required=True, help="Plan JSON path")

    subparsers.add_parser("list-plans", help="List saved plan metadata")

    add_parser = subparsers.add_parser("wishlist-add", help="Add or update a destination")
    add_parser.add_argument("--destination", required=True)
    add_parser.add_argument("--note", default="")

    subparsers.add_parser("wishlist-list", help="List wishlist destinations")

    remove_parser = subparsers.add_parser("wishlist-remove", help="Remove one destination")
    remove_parser.add_argument("--destination", required=True)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        root = _resolve_root(args.root)
        if args.command == "save":
            result = save_plan(root, args.plan)
        elif args.command == "list-plans":
            result = {"plans": list_plans(root)}
        elif args.command == "wishlist-add":
            result = wishlist_add(root, args.destination, args.note)
        elif args.command == "wishlist-list":
            result = wishlist_list(root)
        elif args.command == "wishlist-remove":
            result = wishlist_remove(root, args.destination)
        else:
            raise StoreError("Unsupported command")
    except StoreError as exc:
        print("Store error: %s" % exc, file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
