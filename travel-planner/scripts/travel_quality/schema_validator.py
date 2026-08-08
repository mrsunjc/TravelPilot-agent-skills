"""Small dependency-free validator for the JSON Schema subset used by this skill."""

import re

from .common import canonical_json, parse_date, parse_datetime, time_to_minutes, valid_uri


def _resolve_ref(root_schema, reference):
    if not reference.startswith("#/"):
        raise ValueError("Only local JSON Schema references are supported: %s" % reference)
    current = root_schema
    for part in reference[2:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        current = current[part]
    return current


def _type_matches(value, expected):
    if expected == "null":
        return value is None
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return True


def _format_valid(value, format_name):
    if value is None:
        return True
    if format_name == "date":
        return parse_date(value) is not None
    if format_name == "date-time":
        return parse_datetime(value) is not None
    if format_name == "time":
        return time_to_minutes(value) is not None
    if format_name == "uri":
        return valid_uri(value)
    return True


def validate(instance, schema, root_schema=None, path="$"):
    root = root_schema or schema
    errors = []

    if "$ref" in schema:
        referenced = _resolve_ref(root, schema["$ref"])
        return validate(instance, referenced, root, path)

    if "allOf" in schema:
        for branch in schema["allOf"]:
            errors.extend(validate(instance, branch, root, path))
    if "anyOf" in schema:
        branch_errors = [validate(instance, branch, root, path) for branch in schema["anyOf"]]
        if all(items for items in branch_errors):
            errors.append({"path": path, "message": "does not satisfy anyOf"})
    if "oneOf" in schema:
        matches = sum(1 for branch in schema["oneOf"] if not validate(instance, branch, root, path))
        if matches != 1:
            errors.append({"path": path, "message": "must satisfy exactly one oneOf branch"})

    if "const" in schema and instance != schema["const"]:
        errors.append({"path": path, "message": "must equal %r" % schema["const"]})
    if "enum" in schema and instance not in schema["enum"]:
        errors.append({"path": path, "message": "must be one of %r" % schema["enum"]})

    expected = schema.get("type")
    if expected is not None:
        expected_types = expected if isinstance(expected, list) else [expected]
        if not any(_type_matches(instance, item) for item in expected_types):
            errors.append({"path": path, "message": "must have type %s" % expected_types})
            return errors

    if isinstance(instance, str):
        if "minLength" in schema and len(instance) < schema["minLength"]:
            errors.append({"path": path, "message": "is shorter than minLength"})
        if "maxLength" in schema and len(instance) > schema["maxLength"]:
            errors.append({"path": path, "message": "is longer than maxLength"})
        if "pattern" in schema and not re.search(schema["pattern"], instance):
            errors.append({"path": path, "message": "does not match required pattern"})
        if schema.get("format") and not _format_valid(instance, schema["format"]):
            errors.append({"path": path, "message": "is not a valid %s" % schema["format"]})

    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            errors.append({"path": path, "message": "is below minimum"})
        if "maximum" in schema and instance > schema["maximum"]:
            errors.append({"path": path, "message": "is above maximum"})

    if isinstance(instance, list):
        if "minItems" in schema and len(instance) < schema["minItems"]:
            errors.append({"path": path, "message": "has fewer than minItems"})
        if "maxItems" in schema and len(instance) > schema["maxItems"]:
            errors.append({"path": path, "message": "has more than maxItems"})
        if schema.get("uniqueItems"):
            serialized = [canonical_json(item) for item in instance]
            if len(serialized) != len(set(serialized)):
                errors.append({"path": path, "message": "must contain unique items"})
        item_schema = schema.get("items")
        if item_schema:
            for index, item in enumerate(instance):
                errors.extend(validate(item, item_schema, root, "%s[%d]" % (path, index)))

    if isinstance(instance, dict):
        required = schema.get("required") or []
        for key in required:
            if key not in instance:
                errors.append({"path": "%s.%s" % (path, key), "message": "is required"})
        properties = schema.get("properties") or {}
        for key, value in instance.items():
            if key in properties:
                errors.extend(validate(value, properties[key], root, "%s.%s" % (path, key)))
            elif schema.get("additionalProperties") is False:
                errors.append({"path": "%s.%s" % (path, key), "message": "is not allowed"})
            elif isinstance(schema.get("additionalProperties"), dict):
                errors.extend(
                    validate(value, schema["additionalProperties"], root, "%s.%s" % (path, key))
                )
    return errors

