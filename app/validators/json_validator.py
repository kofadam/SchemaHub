import json
import os
import re
from typing import Any, Optional

from jsonschema import Draft202012Validator


# ---------------------------------------------------------------------------
# Limits — configurable via environment variables
# ---------------------------------------------------------------------------

# Maximum nesting depth of a JSON Schema (prevents exponential validation)
MAX_SCHEMA_DEPTH = int(os.getenv("MAX_SCHEMA_DEPTH", "20"))

# Maximum length of a regex pattern (prevents ReDoS via complex patterns)
MAX_PATTERN_LENGTH = int(os.getenv("MAX_PATTERN_LENGTH", "200"))


def _check_schema_depth(obj: Any, current_depth: int = 0) -> int:
    """Recursively find the maximum nesting depth of a schema object."""
    if current_depth > MAX_SCHEMA_DEPTH:
        return current_depth
    if isinstance(obj, dict):
        if not obj:
            return current_depth
        return max(_check_schema_depth(v, current_depth + 1) for v in obj.values())
    if isinstance(obj, list):
        if not obj:
            return current_depth
        return max(_check_schema_depth(v, current_depth) for v in obj)
    return current_depth


def _check_patterns(obj: Any, depth: int = 0) -> Optional[str]:
    """
    Walk the schema and check all regex patterns for:
    - Excessive length
    - Basic catastrophic backtracking heuristics
    """
    if depth > MAX_SCHEMA_DEPTH:
        return None
    if isinstance(obj, dict):
        for key, val in obj.items():
            if key == "pattern" and isinstance(val, str):
                if len(val) > MAX_PATTERN_LENGTH:
                    return f"Pattern too long ({len(val)} chars, max {MAX_PATTERN_LENGTH})"
                # Detect common ReDoS patterns: nested quantifiers like (a+)+, (a*)*
                if re.search(r'(\([^)]*[+*]\)[+*]|\([^)]*\)\{[0-9]+,\}[+*])', val):
                    return f"Pattern rejected: potentially catastrophic backtracking detected"
            result = _check_patterns(val, depth + 1)
            if result:
                return result
    elif isinstance(obj, list):
        for item in obj:
            result = _check_patterns(item, depth)
            if result:
                return result
    return None


def validate_json(data: str, schema: Any) -> list[dict]:
    """
    Validate a JSON string against a JSON Schema 2020-12 (dict).
    Returns a list of error dicts with keys: field, message.

    Security:
    - Checks schema nesting depth to prevent exponential validation time
    - Checks regex patterns for ReDoS vulnerabilities
    """
    try:
        instance = json.loads(data)
    except json.JSONDecodeError as e:
        return [{"field": None, "message": f"Invalid JSON: {e}"}]

    if not isinstance(schema, dict):
        return [{"field": None, "message": "JSON schema must be a JSON object (dict)"}]

    # Check schema depth
    depth = _check_schema_depth(schema)
    if depth > MAX_SCHEMA_DEPTH:
        return [{"field": None, "message": f"Schema rejected: nesting depth {depth} exceeds maximum of {MAX_SCHEMA_DEPTH}"}]

    # Check regex patterns
    pattern_error = _check_patterns(schema)
    if pattern_error:
        return [{"field": None, "message": f"Schema rejected: {pattern_error}"}]

    validator = Draft202012Validator(schema)
    errors = []
    for err in sorted(validator.iter_errors(instance), key=lambda e: list(e.path)):
        field = ".".join(str(p) for p in err.absolute_path) or None
        errors.append({"field": field, "message": err.message})

    return errors
