# Installation Guide

SchemaHub deploys as a standard Kubernetes workload. It requires:

- A Kubernetes cluster (1.25+)
- A container registry accessible from the cluster
- `kubectl` configured with cluster access
- `cert-manager` installed (for TLS)
- An ingress controller (Contour HTTPProxy manifests provided; adapt for nginx/traefik as needed)

## Prerequisites

### 1. Build and push the image

Download the Swagger UI and ReDoc static assets before building:

```bash
mkdir swagger-static
curl -sLo swagger-static/swagger-ui-bundle.js "https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"
curl -sLo swagger-static/swagger-ui.css        "https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css"
curl -sLo swagger-static/redoc.standalone.js   "https://cdn.jsdelivr.net/npm/redoc@next/bundles/redoc.standalone.js"
curl -sLo swagger-static/favicon.png           "https://fastapi.tiangolo.com/img/favicon.png"
```

Build and push:

```bash
docker build -t your-registry/schemahub:latest .
docker push your-registry/schemahub:latest
```

### 2. Configure secrets

Edit `k8s/redis.yaml` and set a strong Redis password:

```yaml
stringData:
  password: "your-strong-password-here"
```

For production, use an external secrets manager (Vault, Sealed Secrets, External Secrets Operator) instead of plaintext in the manifest.

### 3. Update image reference

Edit `k8s/deployment.yaml` and replace the image placeholder:

```yaml
image: your-registry/schemahub:latest
```

### 4. Configure ingress

Edit `k8s/httpproxy.yaml` and set your hostname and ClusterIssuer:

```yaml
commonName: schemahub.yourdomain.com
dnsNames:
  - schemahub.yourdomain.com
---
fqdn: schemahub.yourdomain.com
```

> If you use nginx or another ingress controller, replace `k8s/httpproxy.yaml` with the appropriate Ingress resource.

---

## Deploy

```bash
# 1. Redis (persistent registry backend)
kubectl apply -f k8s/redis.yaml

# 2. Wait for Redis to be ready
kubectl -n schemahub rollout status deployment/redis

# 3. Deploy SchemaHub
kubectl apply -f k8s/deployment.yaml

# 4. Ingress and TLS
kubectl apply -f k8s/httpproxy.yaml

# 5. PodDisruptionBudget (recommended for production)
kubectl apply -f k8s/pdb.yaml
```

### Optional — Prometheus monitoring

If you use the Prometheus Operator, deploy the ServiceMonitor:

```bash
kubectl apply -f k8s/servicemonitor.yaml
```

> Adjust the `release` label in `servicemonitor.yaml` to match your Prometheus Operator's `serviceMonitorSelector`.

---

## Verify

```bash
# All pods running
kubectl -n schemahub get pods

# Health check
curl https://schemahub.yourdomain.com/healthz | jq .
```

Expected response:

```json
{
  "status": "ok",
  "version": "2.1.0",
  "registry": {
    "backend": "redis",
    "available": true
  }
}
```

---

## Local development

```bash
# Build local image (no registry required)
docker build -f Dockerfile.local -t schemahub:local .

# Run
docker run --rm -p 8000:8000 schemahub:local

# Open
open http://localhost:8000
```

> Without Redis, the schema registry falls back to in-memory storage. Schemas are lost on restart but all other functionality works normally.

---

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `REDIS_HOST` | `redis` | Redis hostname |
| `REDIS_PORT` | `6379` | Redis port |
| `REDIS_PASSWORD` | `` | Redis password |
| `REDIS_DB` | `0` | Redis database index |
| `MAX_BODY_BYTES` | `5242880` | Max HTTP request body size (5MB) |
| `MAX_DATA_BYTES` | `1048576` | Max `data` field size (1MB) |
| `MAX_SCHEMA_BYTES` | `262144` | Max `schema_inline` field size (256KB) |

---

## Upgrading

SchemaHub uses a layered image build pattern for upgrades. To update only application code without reinstalling dependencies:

```dockerfile
FROM your-registry/schemahub:previous-version

WORKDIR /app
USER root

COPY app/main.py .
# ... other changed files

USER appuser
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

This keeps build times short when only Python or static files change.
