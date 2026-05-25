<div align="center">

<img src="docs/logo.svg" alt="SchemaHub" width="80"/>

# SchemaHub

**Validate, generate, and build schemas for JSON, XML, and CSV — with a browser UI and a REST API.**

[![Python](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688.svg)](https://fastapi.tiangolo.com/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

</div>

---

## What is SchemaHub?

SchemaHub is a self-hosted schema management service designed for data pipelines, platform teams, and anyone who validates structured data at scale. It exposes a REST API backed by three browser-based tools:

| Tool | URL | Description |
|------|-----|-------------|
| **Landing page** | `/` | Overview, live stats, and navigation hub |
| **Schema Generator** | `/ui` | Paste sample data → auto-generate a schema |
| **Visual Builder** | `/builder` | Build schemas manually with constraints, enums, and conditional rules |
| **API Docs** | `/docs` | Interactive Swagger UI |
| **API Reference** | `/redoc` | Read-only ReDoc reference |

## Features

- **Three formats** — JSON ([JSON Schema 2020-12](https://json-schema.org/draft/2020-12)), XML ([XSD](https://www.w3.org/XML/Schema)), CSV ([Frictionless Table Schema](https://specs.frictionlessdata.io/table-schema/))
- **Schema registry** — register schemas once, reference by UUID from any pipeline
- **Persistent storage** — Redis-backed registry survives restarts and scales across replicas
- **Visual builder** — works for JSON Schema and XSD; supports patterns, min/max, enums, nested objects, `if/then/else` conditionals, and `minOccurs`/`maxOccurs` for XML elements
- **Schema generation** — auto-generate schemas from sample data for all three formats, including XSD inference from sample XML
- **Generator → Builder flow** — generate from sample data, open in the Visual Builder to refine, register to the registry
- **Hardened by default** — XML bomb / XXE protection via defusedxml, ReDoS prevention in JSON Schema patterns, configurable size and registry caps
- **Production-ready** — structured JSON logging, global rate limiting (with in-memory fallback when Redis is unavailable), request size limits, PodDisruptionBudget
- **Observable** — structured logs for Loki, `/metrics` endpoint for Prometheus, Grafana dashboard included
- **Unified UI** — consistent header and navigation across the landing page, Generator, Builder, Swagger UI, and ReDoc

<img width="3054" height="1932" alt="image" src="https://github.com/user-attachments/assets/90c3e9b8-36e2-4226-8ea9-91a66365f3f3" />

<img width="3054" height="1932" alt="image" src="https://github.com/user-attachments/assets/b5efa921-4828-4da2-8c09-13b8a08a9eea" />

<img width="3054" height="1932" alt="image" src="https://github.com/user-attachments/assets/c5dbcac7-54f0-43a5-90aa-95d76e970a28" />

---

## Quick start

### 1. Clone and download assets

```bash
git clone https://github.com/kofadam/schemahub.git
cd schemahub

curl -sLo swagger-static/swagger-ui-bundle.js "https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"
curl -sLo swagger-static/swagger-ui.css        "https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css"
curl -sLo swagger-static/redoc.standalone.js   "https://unpkg.com/redoc@latest/bundles/redoc.standalone.js"
curl -sLo swagger-static/favicon.png           "https://fastapi.tiangolo.com/img/favicon.png"
```

> `swagger-static/` already exists in the repo — no need to create it.

### 2a. Run with Docker Compose (recommended — includes Redis)

```bash
docker compose up --build
```

Open `http://localhost:8000`. The schema registry is persistent across restarts.

```bash
# Stop
docker compose down

# Stop and wipe Redis data
docker compose down -v
```

### 2b. Run with Docker only (no Redis — in-memory registry)

```bash
docker build -f Dockerfile.local -t schemahub:local .
docker run --rm -p 8000:8000 schemahub:local
```

> Without Redis the registry is in-memory — schemas are lost on restart. All other features work normally.

## API

### Validate data

```bash
curl -s http://localhost:8000/validate \
  -H "Content-Type: application/json" \
  -d '{
    "format": "json",
    "data": "{\"name\": \"Alice\", \"age\": 30}",
    "schema_inline": {
      "type": "object",
      "properties": {
        "name": {"type": "string"},
        "age":  {"type": "integer", "minimum": 0}
      },
      "required": ["name", "age"]
    }
  }' | jq .
```

```json
{
  "valid": true,
  "format": "json",
  "errors": []
}
```

### Generate a schema from sample data

```bash
curl -s http://localhost:8000/generate-schema \
  -H "Content-Type: application/json" \
  -d '{
    "format": "json",
    "data": "{\"id\": 1, \"name\": \"Alice\", \"active\": true}"
  }' | jq .schema
```

### Register a schema and validate by ID

```bash
# Register
SCHEMA_ID=$(curl -s http://localhost:8000/schemas \
  -X POST \
  -H "Content-Type: application/json" \
  -d '{
    "format": "json",
    "description": "User object",
    "schema_def": {
      "type": "object",
      "properties": {"name": {"type": "string"}},
      "required": ["name"]
    }
  }' | jq -r '.schema_id')

# Validate using the ID
curl -s http://localhost:8000/validate \
  -X POST \
  -H "Content-Type: application/json" \
  -d "{\"format\":\"json\",\"data\":\"{\\\"name\\\":\\\"Alice\\\"}\",\"schema_id\":\"$SCHEMA_ID\"}" | jq .
```

### Full pipeline (generate → register → validate)

```bash
JSON_DATA='{"id":1,"name":"Alice","email":"alice@example.com","active":true}'

SCHEMA=$(curl -s http://localhost:8000/generate-schema \
  -H "Content-Type: application/json" \
  -d "{\"format\":\"json\",\"data\":$(echo $JSON_DATA | jq -R '.')}" \
  | jq '.schema')

SCHEMA_ID=$(curl -s http://localhost:8000/schemas \
  -X POST \
  -H "Content-Type: application/json" \
  -d "{\"format\":\"json\",\"description\":\"My schema\",\"schema_def\":$SCHEMA}" \
  | jq -r '.schema_id')

curl -s http://localhost:8000/validate \
  -X POST \
  -H "Content-Type: application/json" \
  -d "{\"format\":\"json\",\"data\":$(echo $JSON_DATA | jq -R '.'),\"schema_id\":\"$SCHEMA_ID\"}" \
  | jq .
```

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/validate` | Validate data against a schema |
| `POST` | `/generate-schema` | Generate a schema from sample data |
| `POST` | `/schemas` | Register a schema |
| `GET` | `/schemas` | List all registered schemas |
| `GET` | `/schemas/{id}` | Get a schema by ID |
| `DELETE` | `/schemas/{id}` | Delete a schema |
| `GET` | `/healthz` | Health check with registry status |
| `GET` | `/metrics` | Prometheus metrics |
| `GET` | `/stats` | Live stats (registry size, request count) |

Full interactive documentation at `/docs`.

## Tech stack

| Component | Purpose |
|-----------|---------|
| [FastAPI](https://fastapi.tiangolo.com/) | HTTP API framework |
| [jsonschema](https://python-jsonschema.readthedocs.io/) | JSON Schema 2020-12 validation |
| [xmlschema](https://xmlschema.readthedocs.io/) | XML + XSD validation |
| [frictionless](https://framework.frictionlessdata.io/) | CSV + Table Schema validation |
| [Redis](https://redis.io/) | Persistent schema registry |
| [slowapi](https://github.com/laurentS/slowapi) | Rate limiting |
| [prometheus-fastapi-instrumentator](https://github.com/trallnag/prometheus-fastapi-instrumentator) | Prometheus metrics |

## Kubernetes deployment

See [`docs/INSTALL.md`](docs/INSTALL.md) for full deployment instructions including Redis, TLS, ingress, monitoring, and upgrade procedures.

```bash
kubectl apply -f k8s/redis.yaml
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/httpproxy.yaml  # or your ingress of choice
kubectl apply -f k8s/pdb.yaml
```

## Monitoring

SchemaHub ships with a Grafana dashboard (`docs/schema-validator-dashboard.json`) covering:

- Request rate and error rate by endpoint
- P50 / P95 / P99 latency percentiles
- Rate limit (429) and size limit (413) hits
- Registry size over time
- Pod CPU and memory usage
- Structured log panels (errors, slow requests, all traffic)

Import the dashboard JSON directly into Grafana. Variables for Prometheus datasource, Loki datasource, cluster, namespace, pod, and container are pre-configured.

## Project structure

```
schemahub/
├── app/
│   ├── main.py                      # FastAPI application
│   ├── registry.py                  # Redis-backed schema registry
│   ├── logging_middleware.py        # Structured JSON request logging
│   ├── size_limits.py               # Request and field size enforcement
│   ├── static/                      # Web UI pages
│   │   ├── index.html               # Landing page
│   │   ├── generator.html           # Schema Generator (/ui)
│   │   └── builder.html             # Visual Builder (/builder)
│   └── validators/
│       ├── json_validator.py        # JSON Schema 2020-12
│       ├── xml_validator.py         # XSD validation
│       ├── csv_validator.py         # Frictionless Table Schema
│       └── schema_generator.py     # Schema inference engine
├── k8s/
│   ├── deployment.yaml              # Namespace, Deployment, Service
│   ├── redis.yaml                   # Redis Deployment, Service, PVC, Secret
│   ├── httpproxy.yaml               # Contour HTTPProxy + cert-manager Certificate
│   ├── servicemonitor.yaml          # Prometheus ServiceMonitor
│   └── pdb.yaml                     # PodDisruptionBudget
├── docs/
│   ├── INSTALL.md                   # Installation guide
│   ├── schema-validator-kb.md       # User guide (Confluence-ready)
│   ├── schema-validator-dashboard.json  # Grafana dashboard
│   ├── logo.svg                     # SchemaHub logo
│   └── favicon.svg                  # Browser favicon
├── swagger-static/                  # Swagger UI / ReDoc assets (downloaded, not committed)
├── docker-compose.yml               # Local development with Redis
├── Dockerfile                       # Production image
├── Dockerfile.local                 # Local development image
└── requirements.txt
```

## License

MIT
