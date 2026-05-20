import json
from typing import Any

from jsonschema import Draft202012Validator


def validate_json(data: str, schema: Any) -> list[dict]:
    """
    Validate a JSON string against a JSON Schema 2020-12 (dict).
    Returns a list of error dicts with keys: field, message.
    """
    try:
        instance = json.loads(data)
    except json.JSONDecodeError as e:
        return [{"field": None, "message": f"Invalid JSON: {e}"}]

    if not isinstance(schema, dict):
        return [{"field": None, "message": "JSON schema must be a JSON object (dict)"}]

    validator = Draft202012Validator(schema)
    errors = []
    for err in sorted(validator.iter_errors(instance), key=lambda e: list(e.path)):
        field = ".".join(str(p) for p in err.absolute_path) or None
        errors.append({"field": field, "message": err.message})

    return errors
