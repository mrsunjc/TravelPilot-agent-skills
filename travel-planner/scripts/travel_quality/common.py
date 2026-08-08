"""Shared helpers for travel quality checks."""

import hashlib
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlparse


SENSITIVE_KEY_PATTERN = re.compile(
    r"(^|_)(api[_-]?key|access[_-]?token|refresh[_-]?token|password|passwd|secret|"
    r"authorization|cookie|session|passport|id[_-]?card|credit[_-]?card|cvv|"
    r"booking[_-]?(code|reference)|verification[_-]?code)($|_)",
    re.IGNORECASE,
)


def load_json(path):
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path, value):
    rendered = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered, encoding="utf-8")


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def value_digest(value):
    encoded = canonical_json(value).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def document_digest(document, omitted_keys=None):
    omitted = set(omitted_keys or [])
    cleaned = {key: value for key, value in document.items() if key not in omitted}
    return value_digest(cleaned)


def utc_now_text():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_datetime(value):
    if not isinstance(value, str) or not value:
        return None
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_date(value):
    if not isinstance(value, str) or not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def time_to_minutes(value):
    if not isinstance(value, str) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
        return None
    hour, minute = value.split(":")
    return int(hour) * 60 + int(minute)


def valid_uri(value):
    if not isinstance(value, str):
        return False
    parsed = urlparse(value)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def finding(code, severity, message, path="$", details=None):
    item = {
        "code": str(code),
        "severity": str(severity),
        "message": str(message),
        "path": str(path),
    }
    if details is not None:
        item["details"] = details
    return item


def find_sensitive_path(value, path="$"):
    if isinstance(value, dict):
        for key, nested in value.items():
            key_text = str(key)
            child = "%s.%s" % (path, key_text)
            if SENSITIVE_KEY_PATTERN.search(key_text):
                return child
            found = find_sensitive_path(nested, child)
            if found:
                return found
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            found = find_sensitive_path(nested, "%s[%d]" % (path, index))
            if found:
                return found
    return None


def unique_index(items, key="id"):
    index = {}
    duplicates = []
    for position, item in enumerate(items or []):
        if not isinstance(item, dict):
            continue
        value = item.get(key)
        if value in index:
            duplicates.append((value, position))
        else:
            index[value] = item
    return index, duplicates

