import csv
import io
import json
from typing import Any

JSON_SCHEMA_VERSION = "https://json-schema.org/draft/2020-12/schema"


def _infer_json_type(value: Any) -> dict:
    """Recursively infer JSON Schema 2020-12 type from a Python value."""
    if value is None:
        return {"type": "null"}
    elif isinstance(value, bool):
        return {"type": "boolean"}
    elif isinstance(value, int):
        return {"type": "integer"}
    elif isinstance(value, float):
        return {"type": "number"}
    elif isinstance(value, str):
        return {"type": "string"}
    elif isinstance(value, list):
        if not value:
            return {"type": "array", "items": {}}
        item_schemas = [_infer_json_type(item) for item in value]
        merged = _merge_schemas(item_schemas)
        return {"type": "array", "items": merged}
    elif isinstance(value, dict):
        return _infer_object_schema(value)
    return {}


def _infer_object_schema(obj: dict) -> dict:
    properties = {}
    for key, val in obj.items():
        properties[key] = _infer_json_type(val)
    return {
        "type": "object",
        "properties": properties,
        "required": list(obj.keys()),
    }


def _merge_schemas(schemas: list[dict]) -> dict:
    """Merge a list of schemas — if all identical return one, else use anyOf."""
    unique = []
    for s in schemas:
        if s not in unique:
            unique.append(s)
    if len(unique) == 1:
        return unique[0]
    return {"anyOf": unique}


def generate_json_schema(data: str) -> dict:
    """
    Generate a JSON Schema 2020-12 object from a sample JSON string.
    Raises ValueError on parse errors.
    """
    try:
        parsed = json.loads(data)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON: {e}")

    if isinstance(parsed, list):
        if not parsed:
            schema = {"type": "array", "items": {}}
        else:
            item_schemas = [_infer_json_type(item) for item in parsed]
            merged = _merge_schemas(item_schemas)
            schema = {"type": "array", "items": merged}
    elif isinstance(parsed, dict):
        schema = _infer_object_schema(parsed)
    else:
        schema = _infer_json_type(parsed)

    # Inject $schema declaration at the top level
    return {"$schema": JSON_SCHEMA_VERSION, **schema}


def _infer_frictionless_type(values: list[str]) -> dict:
    """
    Infer the best Frictionless field type from a list of string cell values.
    Falls back to string if mixed or unrecognisable.
    """
    non_empty = [v for v in values if v.strip() != ""]
    if not non_empty:
        return {"type": "string"}

    # Try integer
    try:
        [int(v) for v in non_empty]
        return {"type": "integer"}
    except ValueError:
        pass

    # Try number
    try:
        [float(v) for v in non_empty]
        return {"type": "number"}
    except ValueError:
        pass

    # Try boolean
    bool_vals = {"true", "false", "1", "0", "yes", "no"}
    if all(v.lower() in bool_vals for v in non_empty):
        return {"type": "boolean"}

    return {"type": "string"}


def generate_csv_schema(data: str) -> dict:
    """
    Generate a Frictionless Table Schema from a sample CSV string.
    Raises ValueError on parse errors.
    """
    try:
        reader = csv.DictReader(io.StringIO(data))
        rows = list(reader)
    except Exception as e:
        raise ValueError(f"Invalid CSV: {e}")

    if not rows:
        raise ValueError("CSV has no data rows — cannot infer schema")

    fieldnames = reader.fieldnames or []
    if not fieldnames:
        raise ValueError("CSV has no header row")

    columns: dict[str, list[str]] = {f: [] for f in fieldnames}
    for row in rows:
        for field in fieldnames:
            columns[field].append(row.get(field) or "")

    fields = []
    for name in fieldnames:
        vals = columns[name]
        type_info = _infer_frictionless_type(vals)
        has_empty = any(v.strip() == "" for v in vals)
        field_def: dict = {"name": name, **type_info}
        if not has_empty:
            field_def["constraints"] = {"required": True}
        fields.append(field_def)

    return {"fields": fields}
