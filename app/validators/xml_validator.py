import io
import signal
import os
from typing import Any

import xmlschema
from defusedxml import ElementTree as DefusedET
import defusedxml


# Patch xmlschema to use defused XML parsing
defusedxml.defuse_stdlib()

# Validation timeout in seconds
XML_VALIDATION_TIMEOUT = int(os.getenv("XML_VALIDATION_TIMEOUT", "10"))


class XMLValidationTimeout(Exception):
    pass


def _timeout_handler(signum, frame):
    raise XMLValidationTimeout("XML validation timed out")


def validate_xml(data: str, schema: Any) -> list[dict]:
    """
    Validate an XML string against an XSD schema string.
    Returns a list of error dicts with keys: field, message.

    Security:
    - Uses defusedxml to prevent XML bomb / billion laughs / XXE attacks
    - Enforces a validation timeout to prevent ReDoS via complex XSD patterns
    """
    if not isinstance(schema, str):
        return [{"field": None, "message": "XML schema must be an XSD string"}]

    # Pre-validate XML safety using defusedxml before passing to xmlschema
    try:
        DefusedET.fromstring(data)
    except defusedxml.DTDForbidden:
        return [{"field": None, "message": "XML rejected: DTD declarations are not allowed"}]
    except defusedxml.EntitiesForbidden:
        return [{"field": None, "message": "XML rejected: entity declarations are not allowed"}]
    except defusedxml.ExternalReferenceForbidden:
        return [{"field": None, "message": "XML rejected: external references are not allowed"}]
    except Exception as e:
        return [{"field": None, "message": f"XML parse error: {e}"}]

    try:
        xsd = xmlschema.XMLSchema(io.StringIO(schema))
    except Exception as e:
        return [{"field": None, "message": f"Invalid XSD schema: {e}"}]

    # Set timeout to guard against complex XSD patterns causing excessive CPU use
    old_handler = None
    try:
        if hasattr(signal, 'SIGALRM'):  # Unix only
            old_handler = signal.signal(signal.SIGALRM, _timeout_handler)
            signal.alarm(XML_VALIDATION_TIMEOUT)

        errors = []
        for error in xsd.iter_errors(io.StringIO(data)):
            errors.append({
                "field": str(error.path) if error.path else None,
                "message": error.reason or str(error),
            })
        return errors

    except XMLValidationTimeout:
        return [{"field": None, "message": f"XML validation timed out after {XML_VALIDATION_TIMEOUT}s — schema or data may be too complex"}]
    except Exception as e:
        return [{"field": None, "message": f"XML validation error: {e}"}]
    finally:
        if hasattr(signal, 'SIGALRM') and old_handler is not None:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)
