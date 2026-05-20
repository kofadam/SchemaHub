import io
from typing import Any

import xmlschema


def validate_xml(data: str, schema: Any) -> list[dict]:
    """
    Validate an XML string against an XSD schema string.
    Returns a list of error dicts with keys: field, message.
    """
    if not isinstance(schema, str):
        return [{"field": None, "message": "XML schema must be an XSD string"}]

    try:
        xsd = xmlschema.XMLSchema(io.StringIO(schema))
    except Exception as e:
        return [{"field": None, "message": f"Invalid XSD schema: {e}"}]

    try:
        errors = []
        for error in xsd.iter_errors(io.StringIO(data)):
            errors.append({
                "field": str(error.path) if error.path else None,
                "message": error.reason or str(error),
            })
        return errors
    except Exception as e:
        return [{"field": None, "message": f"XML parse error: {e}"}]
