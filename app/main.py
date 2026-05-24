import uuid
from typing import Annotated, Any, Optional

from fastapi import Body, FastAPI, HTTPException, Request, status
from fastapi.openapi.docs import get_swagger_ui_html, get_redoc_html
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from prometheus_fastapi_instrumentator import Instrumentator
from prometheus_client import Gauge
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from validators.json_validator import validate_json
from validators.xml_validator import validate_xml
from validators.csv_validator import validate_csv
from validators.schema_generator import generate_json_schema, generate_csv_schema, generate_xml_schema
import registry as reg
from logging_middleware import JSONLoggingMiddleware, setup_logging
from size_limits import BodySizeLimitMiddleware, check_field_sizes, MAX_DATA_BYTES, MAX_SCHEMA_BYTES


# ---------------------------------------------------------------------------
# OpenAPI metadata
# ---------------------------------------------------------------------------

DESCRIPTION = """
Validates **JSON**, **XML**, and **CSV** data against schemas.

## How it works

Send your data and a schema in a single `POST /validate` request.
The service returns whether the data is valid and, if not, a list of errors
with the exact field and row that failed.

## Schema formats

| Format | Schema type | Standard |
|--------|-------------|----------|
| `json` | JSON object | [JSON Schema 2020-12](https://json-schema.org/draft/2020-12) |
| `xml`  | XSD string  | [W3C XML Schema](https://www.w3.org/XML/Schema) |
| `csv`  | JSON object | [Frictionless Table Schema](https://specs.frictionlessdata.io/table-schema/) |

## Schema registry

Instead of sending the schema on every request, you can register it once
with `POST /schemas` and get back a `schema_id`. Pipeline jobs then reference
the ID — useful when the same schema is shared across many calls.

> **Note:** The schema registry is backed by Redis and persists across restarts.

## Self-signed TLS

This service uses an internal CA certificate. Callers must either:
- Import the internal CA into their trust store, **or**
- Pass `-k` / `--insecure` in curl (testing only), **or**
- Set `REQUESTS_CA_BUNDLE` for Python clients
"""

# Disable the default /docs and /redoc so we can override them with local assets
app = FastAPI(
    title="Schema Validator",
    description=DESCRIPTION,
    version="2.1.0",
    contact={
        "name": "Platform Engineering",
    },
    license_info={
        "name": "Internal — not for public distribution",
    },
    openapi_tags=[
        {
            "name": "Validation",
            "description": "Validate data against a schema — inline or from the registry.",
        },
        {
            "name": "Schema Registry",
            "description": "Store and manage reusable schemas. Reference them by ID in `/validate`.",
        },
        {
            "name": "Schema Generator",
            "description": "Generate schemas automatically from sample data. Supports JSON and CSV.",
        },
    ],
    docs_url=None,    # disable default CDN-based docs
    redoc_url=None,   # disable default CDN-based redoc
)

# Serve swagger static files from /static — bundled inside the container image
# The files are copied in via Dockerfile from swagger-static/
app.mount("/static", StaticFiles(directory="static"), name="static")

# ---------------------------------------------------------------------------
# Logging, rate limiting, size limits, metrics
# ---------------------------------------------------------------------------

setup_logging()

# Rate limiter — global limits, Redis-backed for shared state across replicas
# Using a fixed key so all requests share the same counter (global rate limit)
# Per-IP limiting is not useful behind Contour where all traffic shares one IP
#
# Storage backend selection:
#   - Try Redis first (shared state across replicas)
#   - Fall back to in-memory if Redis is unavailable (single-replica fallback)
def _build_limiter() -> Limiter:
    redis_uri = f"redis://:{reg.REDIS_PASSWORD}@{reg.REDIS_HOST}:{reg.REDIS_PORT}/{reg.REDIS_DB}"
    try:
        # Test Redis connectivity before using it as rate limit backend
        import redis as _redis
        client = _redis.Redis(
            host=reg.REDIS_HOST,
            port=reg.REDIS_PORT,
            password=reg.REDIS_PASSWORD,
            db=reg.REDIS_DB,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        client.ping()
        client.close()
        return Limiter(
            key_func=lambda request: "global",
            storage_uri=redis_uri,
            default_limits=["300/minute"],
        )
    except Exception as e:
        import logging
        logging.getLogger("schema_validator").warning(
            f"Rate limiter falling back to in-memory storage (Redis unavailable: {e})"
        )
        # In-memory fallback — limits enforced per-process, not shared across replicas
        return Limiter(
            key_func=lambda request: "global",
            storage_uri="memory://",
            default_limits=["300/minute"],
        )

limiter = _build_limiter()
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Middleware (order matters — outermost first)
app.add_middleware(JSONLoggingMiddleware)
app.add_middleware(BodySizeLimitMiddleware)

# Prometheus metrics — auto-instruments all endpoints
Instrumentator(
    should_group_status_codes=False,
    excluded_handlers=["/healthz", "/metrics", "/static"],
).instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)

# Custom gauge — registry schema count
registry_size_gauge = Gauge(
    "schema_validator_registry_size",
    "Number of schemas currently stored in the registry",
)



# ---------------------------------------------------------------------------
# Docs endpoints — served from local static files (air-gap safe)
# ---------------------------------------------------------------------------

@app.get("/docs", include_in_schema=False)
def docs():
    return get_swagger_ui_html(
        openapi_url="/openapi.json",
        title="Schema Validator",
        swagger_js_url="/static/swagger-ui-bundle.js",
        swagger_css_url="/static/swagger-ui.css",
        swagger_favicon_url="/static/favicon.svg",
    )


@app.get("/redoc", include_in_schema=False)
def redoc():
    return get_redoc_html(
        openapi_url="/openapi.json",
        title="Schema Validator",
        redoc_js_url="/static/redoc.standalone.js",
        redoc_favicon_url="/static/favicon.svg",
    )


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class ValidateRequest(BaseModel):
    format: str = Field(
        ...,
        description="Data format to validate. Must be one of: `json`, `xml`, `csv`.",
    )
    data: str = Field(
        ...,
        description="The raw data to validate, as a string.",
    )
    schema_inline: Optional[Any] = Field(
        default=None,
        description=(
            "Schema definition provided inline. "
            "For `json`: a JSON Schema 2020-12 object. "
            "For `xml`: an XSD document as a string. "
            "For `csv`: a Frictionless Table Schema object. "
            "Either `schema_inline` or `schema_id` must be provided."
        ),
    )
    schema_id: Optional[str] = Field(
        default=None,
        description=(
            "ID of a previously registered schema from the schema registry. "
            "Use this instead of `schema_inline` to avoid repeating the schema on every call. "
            "Either `schema_inline` or `schema_id` must be provided."
        ),
    )


class ValidationError(BaseModel):
    row: Optional[int] = Field(
        default=None,
        description="Row number where the error occurred (1-based, CSV only). `null` for JSON and XML.",
    )
    field: Optional[str] = Field(
        default=None,
        description="Field or path where the error occurred. `null` if the error applies to the whole document.",
    )
    message: str = Field(
        ...,
        description="Human-readable description of the validation error.",
    )


class ValidateResponse(BaseModel):
    valid: bool = Field(..., description="`true` if the data passed all schema checks, `false` otherwise.")
    format: str = Field(..., description="The format that was validated (`json`, `xml`, or `csv`).")
    errors: list[ValidationError] = Field(
        default=[],
        description="List of validation errors. Empty when `valid` is `true`.",
    )


class SchemaRegisterRequest(BaseModel):
    format: str = Field(
        ...,
        description="Format this schema applies to. Must be one of: `json`, `xml`, `csv`.",
    )
    schema_def: Any = Field(
        ...,
        description=(
            "The schema definition. "
            "For `json`: a JSON Schema 2020-12 object. "
            "For `xml`: an XSD document as a string. "
            "For `csv`: a Frictionless Table Schema object."
        ),
    )
    description: Optional[str] = Field(
        default=None,
        description="Optional human-readable label for this schema (shown in registry listings).",
    )


class SchemaRegisterResponse(BaseModel):
    schema_id: str = Field(..., description="UUID assigned to this schema. Use it in `POST /validate` as `schema_id`.")
    format: str = Field(..., description="Format this schema applies to.")
    description: Optional[str] = Field(default=None, description="Description provided at registration time.")


# ---------------------------------------------------------------------------
# Examples for Swagger UI
# ---------------------------------------------------------------------------

VALIDATE_EXAMPLES = {
    "json_inline": {
        "summary": "JSON — inline schema",
        "value": {
            "format": "json",
            "data": '{"name": "Alice", "age": 30}',
            "schema_inline": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "age": {"type": "integer", "minimum": 0},
                },
                "required": ["name", "age"],
            },
        },
    },
    "json_invalid": {
        "summary": "JSON — invalid data (age below minimum)",
        "value": {
            "format": "json",
            "data": '{"name": "Alice", "age": -5}',
            "schema_inline": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "age": {"type": "integer", "minimum": 0},
                },
                "required": ["name", "age"],
            },
        },
    },
    "json_registry": {
        "summary": "JSON — schema from registry",
        "value": {
            "format": "json",
            "data": '{"name": "Alice", "age": 30}',
            "schema_id": "paste-your-schema-id-here",
        },
    },
    "xml_inline": {
        "summary": "XML — inline XSD",
        "value": {
            "format": "xml",
            "data": "<person><name>Alice</name><age>30</age></person>",
            "schema_inline": (
                '<?xml version="1.0"?>'
                '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">'
                '<xs:element name="person">'
                "<xs:complexType><xs:sequence>"
                '<xs:element name="name" type="xs:string"/>'
                '<xs:element name="age" type="xs:integer"/>'
                "</xs:sequence></xs:complexType>"
                "</xs:element></xs:schema>"
            ),
        },
    },
    "csv_inline": {
        "summary": "CSV — inline Table Schema",
        "value": {
            "format": "csv",
            "data": "id,email,age\n1,alice@example.com,30\n2,bob@example.com,25",
            "schema_inline": {
                "fields": [
                    {"name": "id",    "type": "integer", "constraints": {"required": True}},
                    {"name": "email", "type": "string",  "constraints": {"required": True}},
                    {"name": "age",   "type": "integer", "constraints": {"minimum": 0}},
                ]
            },
        },
    },
    "csv_invalid": {
        "summary": "CSV — invalid data (missing required email)",
        "value": {
            "format": "csv",
            "data": "id,email,age\n1,,30\n2,bob@example.com,25",
            "schema_inline": {
                "fields": [
                    {"name": "id",    "type": "integer", "constraints": {"required": True}},
                    {"name": "email", "type": "string",  "constraints": {"required": True}},
                    {"name": "age",   "type": "integer", "constraints": {"minimum": 0}},
                ]
            },
        },
    },
}

SCHEMA_REGISTER_EXAMPLES = {
    "json_schema": {
        "summary": "Register a JSON schema",
        "value": {
            "format": "json",
            "description": "User object — v1",
            "schema_def": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "age":  {"type": "integer", "minimum": 0},
                },
                "required": ["name", "age"],
            },
        },
    },
    "csv_schema": {
        "summary": "Register a CSV Table Schema",
        "value": {
            "format": "csv",
            "description": "Employee import file",
            "schema_def": {
                "fields": [
                    {"name": "id",         "type": "integer", "constraints": {"required": True}},
                    {"name": "email",      "type": "string",  "constraints": {"required": True}},
                    {"name": "department", "type": "string"},
                ]
            },
        },
    },
    "xml_schema": {
        "summary": "Register an XML/XSD schema",
        "value": {
            "format": "xml",
            "description": "Person element",
            "schema_def": (
                '<?xml version="1.0"?>'
                '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">'
                '<xs:element name="person">'
                "<xs:complexType><xs:sequence>"
                '<xs:element name="name" type="xs:string"/>'
                '<xs:element name="age" type="xs:integer"/>'
                "</xs:sequence></xs:complexType>"
                "</xs:element></xs:schema>"
            ),
        },
    },
}


# ---------------------------------------------------------------------------
# Validation endpoint
# ---------------------------------------------------------------------------

@app.post(
    "/validate",
    response_model=ValidateResponse,
    summary="Validate data against a schema",
    tags=["Validation"],
    responses={
        200: {"description": "Validation completed. Check the `valid` field — errors are listed even on 200."},
        400: {"description": "Bad request — unsupported format, or neither `schema_inline` nor `schema_id` provided."},
        404: {"description": "`schema_id` was provided but not found in the registry."},
        422: {"description": "The validation engine encountered an unexpected error (e.g. malformed XSD)."},
    },
)
@limiter.limit("120/minute")
def validate(
    request: Request,
    req: Annotated[ValidateRequest, Body(openapi_examples=VALIDATE_EXAMPLES)],
):
    check_field_sizes(data=req.data, schema_inline=req.schema_inline)
    """
    Validate data against a schema.

    - Provide the data as a raw string in `data`.
    - Provide the schema either **inline** (`schema_inline`) or by **registry ID** (`schema_id`).
    - The response always returns HTTP 200. Check `valid: false` and the `errors` list for failures.
    """
    fmt = req.format.lower()
    if fmt not in ("json", "xml", "csv"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported format '{fmt}'. Must be one of: json, xml, csv",
        )

    schema = None
    if req.schema_id:
        entry = reg.get_schema(req.schema_id)
        if not entry:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Schema ID '{req.schema_id}' not found in registry",
            )
        if entry["format"] != fmt:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Schema ID '{req.schema_id}' is for format '{entry['format']}', but request format is '{fmt}'",
            )
        schema = entry["schema"]
    elif req.schema_inline is not None:
        schema = req.schema_inline
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either 'schema_inline' or 'schema_id' must be provided",
        )

    try:
        if fmt == "json":
            errors = validate_json(req.data, schema)
        elif fmt == "xml":
            errors = validate_xml(req.data, schema)
        elif fmt == "csv":
            errors = validate_csv(req.data, schema)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Validation engine error: {str(e)}",
        )

    return ValidateResponse(
        valid=len(errors) == 0,
        format=fmt,
        errors=errors,
    )


# ---------------------------------------------------------------------------
# Schema registry endpoints
# ---------------------------------------------------------------------------

@app.post(
    "/schemas",
    response_model=SchemaRegisterResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a schema",
    tags=["Schema Registry"],
    responses={
        201: {"description": "Schema registered. The returned `schema_id` can be used in `POST /validate`."},
        400: {"description": "Unsupported format."},
    },
)
def register_schema(
    req: Annotated[SchemaRegisterRequest, Body(openapi_examples=SCHEMA_REGISTER_EXAMPLES)],
):
    """
    Store a schema in the registry and receive a `schema_id`.

    Use the `schema_id` in subsequent `POST /validate` calls instead of
    repeating the full schema definition each time.

    > **Note:** The registry is in-memory. Schemas do not survive pod restarts.
    """
    fmt = req.format.lower()
    if fmt not in ("json", "xml", "csv"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported format '{fmt}'",
        )
    try:
        schema_id = reg.register_schema(
            format=fmt,
            schema_def=req.schema_def,
            description=req.description,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(e))
    return SchemaRegisterResponse(schema_id=schema_id, format=fmt, description=req.description)


@app.get(
    "/schemas",
    summary="List all registered schemas",
    tags=["Schema Registry"],
)
def list_schemas():
    """Return a summary list of all schemas currently in the registry."""
    return reg.list_schemas()


@app.get(
    "/schemas/{schema_id}",
    summary="Get a schema by ID",
    tags=["Schema Registry"],
    responses={
        200: {"description": "Schema found and returned."},
        404: {"description": "Schema not found."},
    },
)
def get_schema(schema_id: str):
    """Retrieve the full schema definition for a given `schema_id`."""
    entry = reg.get_schema(schema_id)
    if not entry:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schema not found")
    return {"schema_id": schema_id, **entry}


@app.delete(
    "/schemas/{schema_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a schema",
    tags=["Schema Registry"],
    responses={
        204: {"description": "Schema deleted."},
        404: {"description": "Schema not found."},
    },
)
def delete_schema(schema_id: str):
    """Remove a schema from the registry by its ID."""
    if not reg.delete_schema(schema_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schema not found")


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/healthz", include_in_schema=False)
def healthz():
    status_info = reg.registry_status()
    # Update registry size gauge
    try:
        schemas = reg.list_schemas()
        registry_size_gauge.set(len(schemas))
    except Exception:
        pass
    return {
        "status": "ok",
        "version": "2.1.0",
        "registry": status_info,
        "limits": {
            "max_body_bytes": 5 * 1024 * 1024,
            "max_data_bytes": MAX_DATA_BYTES,
            "max_schema_bytes": MAX_SCHEMA_BYTES,
        },
    }


@app.get("/stats", include_in_schema=False)
def stats():
    """Live stats for the landing page — registry size and request counter."""
    schemas = reg.list_schemas()
    return {
        "registry_size": len(schemas),
        "requests_24h": reg.get_requests_last_24h(),
        "registry_backend": reg.registry_status().get("backend", "unknown"),
    }


@app.get("/", include_in_schema=False)
def landing():
    """Serve the SchemaHub landing page."""
    with open("static/index.html", "r") as f:
        return HTMLResponse(content=f.read())


# ---------------------------------------------------------------------------
# Schema Generator
# ---------------------------------------------------------------------------

GENERATE_EXAMPLES = {
    "json_sample": {
        "summary": "Generate from JSON sample",
        "value": {
            "format": "json",
            "data": '{"id": 1, "name": "Alice", "email": "alice@example.com", "active": true}',
        },
    },
    "csv_sample": {
        "summary": "Generate from CSV sample",
        "value": {
            "format": "csv",
            "data": "id,name,email,age\n1,Alice,alice@example.com,30\n2,Bob,bob@example.com,25",
        },
    },
    "xml_sample": {
        "summary": "Generate XSD from XML sample",
        "value": {
            "format": "xml",
            "data": "<person id=\"1\"><name>Alice</name><age>30</age><active>true</active></person>",
        },
    },
}


class GenerateSchemaRequest(BaseModel):
    format: str = Field(
        ...,
        description="Format to generate a schema for. Supported: `json`, `csv`, `xml`.",
    )
    data: str = Field(
        ...,
        description="A representative sample of the data to infer the schema from.",
    )


class GenerateSchemaResponse(BaseModel):
    format: str = Field(..., description="The format the schema was generated for.")
    schema_: Any = Field(
        ...,
        alias="schema",
        description="The generated schema. JSON Schema 2020-12 for `json`, Frictionless Table Schema for `csv`, XSD string for `xml`.",
    )

    model_config = {"populate_by_name": True}


@app.post(
    "/generate-schema",
    response_model=GenerateSchemaResponse,
    summary="Generate a schema from sample data",
    tags=["Schema Generator"],
    responses={
        200: {"description": "Schema successfully generated."},
        400: {"description": "Unsupported format or malformed input data."},
    },
)
@limiter.limit("60/minute")
def generate_schema(
    request: Request,
    req: Annotated[GenerateSchemaRequest, Body(openapi_examples=GENERATE_EXAMPLES)],
):
    check_field_sizes(data=req.data)
    """
    Generate a schema from a sample of data.

    - **JSON** → produces a JSON Schema 2020-12 object
    - **CSV** → produces a Frictionless Table Schema object
    - **XML** → produces a basic XSD string (review before production use)

    The generated schema can be used directly in `POST /validate` as `schema_inline`,
    or registered via `POST /schemas` to get a reusable `schema_id`.
    """
    fmt = req.format.lower()

    if fmt not in ("json", "csv", "xml"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported format '{fmt}'. Supported formats for generation: json, csv, xml.",
        )

    try:
        if fmt == "json":
            schema = generate_json_schema(req.data)
        elif fmt == "csv":
            schema = generate_csv_schema(req.data)
        elif fmt == "xml":
            schema = generate_xml_schema(req.data)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    return GenerateSchemaResponse(format=fmt, schema=schema)


@app.get("/ui", include_in_schema=False)
def generator_ui():
    """Serve the schema generator web UI."""
    with open("static/generator.html", "r") as f:
        return HTMLResponse(content=f.read())


@app.get("/builder", include_in_schema=False)
def builder_ui():
    """Serve the visual schema builder web UI."""
    with open("static/builder.html", "r") as f:
        return HTMLResponse(content=f.read())
