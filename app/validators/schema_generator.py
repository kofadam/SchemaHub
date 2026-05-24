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


def _infer_xs_type(text: str) -> str:
    """Infer the best xs: simple type from a text string."""
    if text is None or text.strip() == "":
        return "xs:string"
    v = text.strip()
    # boolean
    if v.lower() in ("true", "false"):
        return "xs:boolean"
    # integer
    try:
        int(v)
        return "xs:integer"
    except ValueError:
        pass
    # decimal
    try:
        float(v)
        return "xs:decimal"
    except ValueError:
        pass
    # date (YYYY-MM-DD)
    import re
    if re.match(r'^\d{4}-\d{2}-\d{2}$', v):
        return "xs:date"
    # dateTime
    if re.match(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}', v):
        return "xs:dateTime"
    return "xs:string"


def _collect_element_info(elements):
    """
    Given a list of same-tag Element instances, collect:
    - child tag names and their occurrence counts
    - attribute names
    - text content types
    """
    child_tags = {}        # tag -> count across all elements
    attr_names = set()
    text_types = set()
    has_children = False

    for el in elements:
        # attributes
        attr_names.update(el.attrib.keys())
        # text
        text = (el.text or "").strip()
        if text:
            text_types.add(_infer_xs_type(text))
        # children
        for child in el:
            tag = child.tag
            # strip namespace if present
            if "}" in tag:
                tag = tag.split("}")[1]
            child_tags[tag] = child_tags.get(tag, 0) + 1
            has_children = True

    return child_tags, attr_names, text_types, has_children


def _build_complex_type(elements, indent: int = 3) -> list[str]:
    """
    Recursively build xs:complexType lines for a list of same-tag elements.
    Returns a list of indented XSD lines.
    """
    pad = "  " * indent
    lines = []

    child_tags, attr_names, text_types, has_children = _collect_element_info(elements)
    total = len(elements)

    if not has_children and not attr_names:
        # Simple element — type determined by text content
        xs_type = next(iter(text_types), "xs:string") if text_types else "xs:string"
        return [xs_type]  # caller will use as type= attribute

    lines.append(f"{pad}<xs:complexType>")

    if has_children:
        lines.append(f"{pad}  <xs:sequence>")
        # Group children by tag and recurse
        for child_tag, count in child_tags.items():
            child_elements = []
            for el in elements:
                for child in el:
                    ctag = child.tag
                    if "}" in ctag:
                        ctag = ctag.split("}")[1]
                    if ctag == child_tag:
                        child_elements.append(child)

            # Determine minOccurs — if count < total elements, it's optional
            min_occurs = "0" if count < total else "1"
            # Determine maxOccurs — if any parent has more than 1 of this child, unbounded
            max_occurs = "1"
            for el in elements:
                child_count = sum(
                    1 for c in el
                    if (c.tag.split("}")[1] if "}" in c.tag else c.tag) == child_tag
                )
                if child_count > 1:
                    max_occurs = "unbounded"
                    break

            child_type_lines = _build_complex_type(child_elements, indent + 3)

            if len(child_type_lines) == 1 and child_type_lines[0].startswith("xs:"):
                # Simple type
                xs_type = child_type_lines[0]
                lines.append(
                    f'{pad}    <xs:element name="{child_tag}" type="{xs_type}"'
                    f' minOccurs="{min_occurs}" maxOccurs="{max_occurs}"/>'
                )
            else:
                lines.append(
                    f'{pad}    <xs:element name="{child_tag}"'
                    f' minOccurs="{min_occurs}" maxOccurs="{max_occurs}">'
                )
                lines.extend(child_type_lines)
                lines.append(f"{pad}    </xs:element>")

        lines.append(f"{pad}  </xs:sequence>")

    # Attributes
    for attr in sorted(attr_names):
        # Sample attribute values across elements
        attr_values = [el.attrib[attr] for el in elements if attr in el.attrib]
        xs_type = _infer_xs_type(attr_values[0]) if attr_values else "xs:string"
        use = "required" if len(attr_values) == total else "optional"
        lines.append(
            f'{pad}  <xs:attribute name="{attr}" type="{xs_type}" use="{use}"/>'
        )

    lines.append(f"{pad}</xs:complexType>")
    return lines


def generate_xml_schema(data: str) -> str:
    """
    Generate a basic XSD string from a sample XML string.
    Returns the XSD as a string.
    Raises ValueError on parse errors.

    The generated XSD covers:
    - Element nesting and sequence
    - minOccurs / maxOccurs inference
    - Attribute names, types, and use (required/optional)
    - Simple type inference (xs:string, xs:integer, xs:decimal, xs:boolean, xs:date, xs:dateTime)

    Note: the result is a starting point — review and refine before using in production.
    """
    from defusedxml import ElementTree as ET

    try:
        root = ET.fromstring(data)
    except Exception as e:
        raise ValueError(f"Invalid XML: {e}")

    # Strip namespace from root tag
    root_tag = root.tag
    if "}" in root_tag:
        root_tag = root_tag.split("}")[1]

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">',
        f'  <!-- Generated from sample XML — review before using in production -->',
        f'  <xs:element name="{root_tag}">',
    ]

    type_lines = _build_complex_type([root], indent=2)

    if len(type_lines) == 1 and type_lines[0].startswith("xs:"):
        # Root is a simple element
        lines[-1] = f'  <xs:element name="{root_tag}" type="{type_lines[0]}"/>'
    else:
        lines.extend(type_lines)
        lines.append("  </xs:element>")

    lines.append("</xs:schema>")
    return "\n".join(lines)
