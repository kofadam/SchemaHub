# Schema Validator — User Guide

**Version:** 2.1.0  
**Service URL:** `https://schema-validator.placeholder.local`  
**Maintained by:** Platform Engineering

---

## Overview

Schema Validator is an internal HTTP API service for validating structured data (JSON, XML, CSV) against schemas. It includes three web interfaces and a fully documented REST API.

| Tool | URL | Purpose |
|------|-----|---------|
| Schema Generator | `/ui` | Paste sample data → auto-generate a schema |
| Visual Builder | `/builder` | Build a schema manually with constraints |
| API Documentation | `/docs` | Interactive Swagger UI — try all endpoints |
| ReDoc | `/redoc` | Read-only API reference |

All interfaces are air-gap safe — no external CDN dependencies.

---

## Concepts

### What is a schema?

A schema is a set of rules that describes the expected structure of your data. The validator checks whether a piece of data conforms to those rules and returns a list of errors if it does not.

| Data format | Schema standard |
|-------------|----------------|
| JSON | [JSON Schema 2020-12](https://json-schema.org/draft/2020-12) |
| XML | [W3C XSD](https://www.w3.org/XML/Schema) |
| CSV | [Frictionless Table Schema](https://specs.frictionlessdata.io/table-schema/) |

### Schema Registry

Schemas can be stored in the service registry and referenced by a UUID (`schema_id`). This is useful for pipelines that validate the same data shape repeatedly — register once, reference by ID forever.

> **Note:** The registry is backed by Redis and persists across pod restarts. Schemas survive deployments.

---

## Tool 1 — Schema Generator (`/ui`)

Use this when you have a sample of your data and want to generate a schema automatically.

### How to use

1. Open `https://schema-validator.placeholder.local/ui`
2. Select the format: **JSON** or **CSV** (XML generation is not supported)
3. Paste a representative sample of your data into the left panel
4. Click **Generate Schema** (or press `Ctrl+Enter`)
5. The generated schema appears in the right panel
6. Click **Copy** to copy it to the clipboard
7. Optionally click **Open in Visual Builder →** to refine it further

### Tips

- For CSV, include a header row and at least 2–3 data rows. More rows means better type inference.
- For JSON, paste a complete object with all fields present. Nested objects are supported.
- The generator infers types (`string`, `integer`, `number`, `boolean`) and marks all fields as `required` by default if they have no empty values.
- Generated schemas include a `$schema` declaration for JSON Schema 2020-12.

### Example — JSON input

```json
{
  "id": 1,
  "name": "Alice",
  "email": "alice@example.com",
  "active": true
}
```

### Example — generated JSON Schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "properties": {
    "id":     { "type": "integer" },
    "name":   { "type": "string" },
    "email":  { "type": "string" },
    "active": { "type": "boolean" }
  },
  "required": ["id", "name", "email", "active"]
}
```

### Example — CSV input

```
id,name,department,active
1,Alice,Engineering,true
2,Bob,Operations,false
```

### Example — generated CSV Table Schema

```json
{
  "fields": [
    { "name": "id",         "type": "integer", "constraints": { "required": true } },
    { "name": "name",       "type": "string",  "constraints": { "required": true } },
    { "name": "department", "type": "string",  "constraints": { "required": true } },
    { "name": "active",     "type": "boolean", "constraints": { "required": true } }
  ]
}
```

---

## Tool 2 — Visual Builder (`/builder`)

Use this when you want to build a schema from scratch with full control over constraints, or when you need conditional validation rules.

### Layout

The page is split into two panels:

- **Left** — the builder form where you add and configure fields
- **Right** — a live JSON Schema 2020-12 preview that updates as you type

### Getting started

1. Open `https://schema-validator.placeholder.local/builder`
2. Optionally fill in the **Title** and **Description** fields at the top
3. Click **＋ Add Field** to add your first property

### Field configuration

Each field row has the following controls:

| Control | Description |
|---------|-------------|
| Field name | The property key (e.g. `email`, `user_id`) |
| Type | `string`, `integer`, `number`, `boolean`, `object`, `array`, `null` |
| Required | Toggle whether this field is required in the schema |
| Description | Optional human-readable description — appears in the schema |
| ⚙ | Toggle the constraints panel for this field |
| ✕ | Remove this field |

### Constraints by type

#### String
| Constraint | Description | Example |
|-----------|-------------|---------|
| Min length | Minimum character count | `1` |
| Max length | Maximum character count | `255` |
| Pattern | Regular expression the value must match | `^[a-z0-9]+$` |
| Format | Semantic format hint | `email`, `date`, `uri`, `uuid` |
| Enum | List of allowed values | `admin`, `user`, `guest` |

#### Integer / Number
| Constraint | Description | Example |
|-----------|-------------|---------|
| Minimum | Inclusive lower bound | `0` |
| Maximum | Inclusive upper bound | `100` |
| Excl. min | Exclusive lower bound | `0` (value must be > 0) |
| Excl. max | Exclusive upper bound | `100` (value must be < 100) |
| Multiple of | Value must be a multiple | `5` |
| Enum | List of allowed values | `1`, `2`, `3` |

#### Array
| Constraint | Description |
|-----------|-------------|
| Min items | Minimum number of elements |
| Max items | Maximum number of elements |
| Unique items | All elements must be distinct |
| Item type | The type each element must be |

### Nested objects

Set a field's type to **object** and a **▼** indicator appears. Click it to expand and add nested fields inside — these can themselves be objects, allowing arbitrarily deep nesting.

### Enum values

For `string`, `integer`, or `number` fields, type a value in the enum input box and press **Enter** or click **＋**. Values appear as tags. Click **×** on a tag to remove it. When enum values are set, all other constraints for that field are ignored.

### Conditional validation (if / then / else)

Conditional validation allows you to make certain fields required only when another field has a specific value.

**Example:** if `role` = `admin` then `permissions` is required; otherwise `department` is required.

**Steps:**

1. Add all your fields first
2. Click **＋ Condition**
3. In the **IF** section, select the trigger field from the dropdown and enter the trigger value
4. In the **THEN** section, click **＋ Add then field** and select which fields become required when the condition is true
5. In the **ELSE** section, click **＋ Add else field** and select which fields become required when the condition is false
6. Either section can be left empty if not needed

The resulting schema uses the JSON Schema 2020-12 `if`/`then`/`else` keywords.

### Registering a schema from the builder

1. Click **↑ Register** in the preview panel header
2. Enter an optional description
3. Click **Register**
4. The `schema_id` appears — click it to copy

---

## Tool 3 — API (`/docs`)

The Swagger UI at `/docs` allows you to call all endpoints interactively from the browser, and documents every request and response shape.

### Endpoints overview

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/validate` | Validate data against a schema |
| `POST` | `/generate-schema` | Generate a schema from sample data |
| `POST` | `/schemas` | Register a schema |
| `GET` | `/schemas` | List all registered schemas |
| `GET` | `/schemas/{schema_id}` | Get a schema by ID |
| `DELETE` | `/schemas/{schema_id}` | Delete a schema |
| `GET` | `/healthz` | Health check |

---

### POST `/validate`

Validates data against a schema. Returns `valid: true/false` and a list of errors.

The schema can be provided **inline** or by **registry ID**.

#### Request body

```json
{
  "format": "json",
  "data": "{\"name\": \"Alice\", \"age\": 30}",
  "schema_inline": {
    "type": "object",
    "properties": {
      "name": { "type": "string" },
      "age":  { "type": "integer", "minimum": 0 }
    },
    "required": ["name", "age"]
  }
}
```

Or using a registered schema:

```json
{
  "format": "json",
  "data": "{\"name\": \"Alice\", \"age\": 30}",
  "schema_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6"
}
```

#### Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `format` | string | ✓ | `json`, `xml`, or `csv` |
| `data` | string | ✓ | The raw data to validate, as a string |
| `schema_inline` | object/string | ✓ (or `schema_id`) | Schema definition inline |
| `schema_id` | string | ✓ (or `schema_inline`) | UUID of a registered schema |

> **Important:** `data` must be a string — not a raw JSON object. Serialize your data before sending.

#### Response — valid

```json
{
  "valid": true,
  "format": "json",
  "errors": []
}
```

#### Response — invalid

```json
{
  "valid": false,
  "format": "json",
  "errors": [
    {
      "row": null,
      "field": "age",
      "message": "-5 is less than the minimum of 0"
    }
  ]
}
```

#### Error fields

| Field | Description |
|-------|-------------|
| `row` | Row number (CSV only, 1-based). `null` for JSON and XML |
| `field` | Field path where the error occurred. `null` for document-level errors |
| `message` | Human-readable error description |

---

### POST `/generate-schema`

Generates a schema from a sample of data. Supports `json` and `csv`. XML is not supported.

#### Request body

```json
{
  "format": "json",
  "data": "{\"id\": 1, \"name\": \"Alice\", \"active\": true}"
}
```

#### Response

```json
{
  "format": "json",
  "schema": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
      "id":     { "type": "integer" },
      "name":   { "type": "string" },
      "active": { "type": "boolean" }
    },
    "required": ["id", "name", "active"]
  }
}
```

---

### POST `/schemas`

Registers a schema and returns a `schema_id` for use in `/validate`.

#### Request body

```json
{
  "format": "json",
  "description": "User object v1",
  "schema_def": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
      "name": { "type": "string" },
      "age":  { "type": "integer", "minimum": 0 }
    },
    "required": ["name", "age"]
  }
}
```

#### Response

```json
{
  "schema_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "format": "json",
  "description": "User object v1"
}
```

---

## End-to-end pipeline example

This example shows the full flow for a JSON pipeline using `curl` and `jq`.

### Step 1 — Generate schema from sample

```bash
JSON_DATA='{"id":1,"name":"Alice","email":"alice@example.com","active":true}'

SCHEMA=$(curl -sk https://schema-validator.placeholder.local/generate-schema \
  -H "Content-Type: application/json" \
  -d "{\"format\":\"json\",\"data\":$(echo $JSON_DATA | jq -R '.')}" \
  | jq '.schema')
```

### Step 2 — Register schema

```bash
SCHEMA_ID=$(curl -sk https://schema-validator.placeholder.local/schemas \
  -X POST \
  -H "Content-Type: application/json" \
  -d "{\"format\":\"json\",\"description\":\"User object\",\"schema_def\":$SCHEMA}" \
  | jq -r '.schema_id')

echo "Registered schema: $SCHEMA_ID"
```

### Step 3 — Validate data

```bash
curl -sk https://schema-validator.placeholder.local/validate \
  -X POST \
  -H "Content-Type: application/json" \
  -d "{\"format\":\"json\",\"data\":$(echo $JSON_DATA | jq -R '.'),\"schema_id\":\"$SCHEMA_ID\"}" \
  | jq .
```

### CSV pipeline

```bash
CSV_FILE=$(mktemp)
cat > $CSV_FILE << 'EOF'
id,name,department,active
1,Alice,Engineering,true
2,Bob,Operations,false
EOF

SCHEMA=$(curl -sk https://schema-validator.placeholder.local/generate-schema \
  -H "Content-Type: application/json" \
  -d "{\"format\":\"csv\",\"data\":$(jq -Rs '.' < $CSV_FILE)}" \
  | jq '.schema')

SCHEMA_ID=$(curl -sk https://schema-validator.placeholder.local/schemas \
  -X POST \
  -H "Content-Type: application/json" \
  -d "{\"format\":\"csv\",\"description\":\"Employee import\",\"schema_def\":$SCHEMA}" \
  | jq -r '.schema_id')

curl -sk https://schema-validator.placeholder.local/validate \
  -X POST \
  -H "Content-Type: application/json" \
  -d "{\"format\":\"csv\",\"data\":$(jq -Rs '.' < $CSV_FILE),\"schema_id\":\"$SCHEMA_ID\"}" \
  | jq .

rm -f $CSV_FILE
```

---

## TLS / Self-signed certificate

The service uses an internal CA certificate. Callers must either:

- Import the internal CA into their trust store, **or**
- Pass `-k` / `--insecure` in curl (testing only — not recommended for pipelines), **or**
- Set `REQUESTS_CA_BUNDLE=/path/to/ca.crt` for Python callers, **or**
- Set `NODE_EXTRA_CA_CERTS=/path/to/ca.crt` for Node.js callers

---

## Health check

```bash
curl -sk https://schema-validator.placeholder.local/healthz | jq .
```

Response when Redis is connected:

```json
{
  "status": "ok",
  "registry": {
    "backend": "redis",
    "host": "redis",
    "port": 6379,
    "available": true
  }
}
```

Response when Redis is unavailable (fallback to in-memory):

```json
{
  "status": "ok",
  "registry": {
    "backend": "memory",
    "available": true,
    "warning": "Redis unavailable — schemas are not persistent"
  }
}
```

---

## Known limitations

| Limitation | Details |
|-----------|---------|
| XML schema generation | Not supported. XSD must be written manually and provided inline or registered via the API. |
| CSV schema generation | Type inference is best-effort. Always review the generated schema before using it in production. |
| Schema registry | Backed by Redis. If Redis is unavailable the service falls back to in-memory storage — schemas registered during a Redis outage will not persist. |
| Conditional validation | The builder supports one `if/then/else` block per schema. Complex multi-condition schemas must be written manually. |

---

## Support

For issues or feature requests contact the Platform Engineering team.
