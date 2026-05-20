import csv
import io
from typing import Any

from frictionless import Resource, Schema, validate as fl_validate


def validate_csv(data: str, schema: Any) -> list[dict]:
    """
    Validate a CSV string against a Frictionless Table Schema (dict).
    Returns a list of error dicts with keys: row, field, message.

    Schema example:
    {
      "fields": [
        {"name": "id",    "type": "integer", "constraints": {"required": true}},
        {"name": "email", "type": "string",  "constraints": {"required": true}},
        {"name": "age",   "type": "integer", "constraints": {"minimum": 0}}
      ]
    }
    """
    if not isinstance(schema, dict):
        return [{"row": None, "field": None, "message": "CSV schema must be a Frictionless Table Schema (dict)"}]

    try:
        fl_schema = Schema.from_descriptor(schema)
    except Exception as e:
        return [{"row": None, "field": None, "message": f"Invalid Table Schema: {e}"}]

    # frictionless 5.x does not accept StringIO or absolute temp file paths.
    # Parse the CSV ourselves into a list of dicts and pass it as inline data.
    try:
        reader = csv.DictReader(io.StringIO(data))
        rows = list(reader)
    except Exception as e:
        return [{"row": None, "field": None, "message": f"CSV parse error: {e}"}]

    try:
        resource = Resource(data=rows, schema=fl_schema)
        report = fl_validate(resource)
    except Exception as e:
        return [{"row": None, "field": None, "message": f"Validation engine error: {e}"}]

    errors = []
    for task in report.tasks:
        for error in task.errors:
            errors.append({
                "row": error.row_number if hasattr(error, "row_number") else None,
                "field": error.field_name if hasattr(error, "field_name") else None,
                "message": error.message,
            })
    return errors
