"""
Structured JSON logging middleware.

Logs every request as a single JSON line to stdout.
Alloy picks this up from the container log stream and ships to Loki.

Log fields:
  ts          - ISO 8601 timestamp
  level       - info / warning / error
  method      - HTTP method
  path        - request path
  status      - HTTP status code
  duration_ms - response time in milliseconds
  size_bytes  - response body size
  client_ip   - X-Forwarded-For or direct client IP
  request_id  - UUID per request for tracing
  error       - error message (only on 5xx)
"""

import json
import logging
import time
import uuid
from typing import Callable

from fastapi import Request, Response
import registry as reg
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp


class JSONLoggingMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp):
        super().__init__(app)
        # Use root logger — uvicorn already sets up stdout handler
        self.logger = logging.getLogger("schema_validator")

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Skip healthz from logs to avoid noise
        if request.url.path == "/healthz":
            return await call_next(request)

        request_id = str(uuid.uuid4())
        start = time.perf_counter()

        # Best-effort client IP — behind Contour all requests come from the proxy
        # X-Forwarded-For carries the original client IP if Contour is configured to set it
        client_ip = (
            request.headers.get("x-forwarded-for", "").split(",")[0].strip()
            or request.headers.get("x-real-ip", "")
            or (request.client.host if request.client else "unknown")
        )

        try:
            response = await call_next(request)
        except Exception as exc:
            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            self._log({
                "ts": self._now(),
                "level": "error",
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status": 500,
                "duration_ms": duration_ms,
                "client_ip": client_ip,
                "error": str(exc),
            })
            raise

        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        size_bytes = int(response.headers.get("content-length", 0))

        level = "error" if response.status_code >= 500 else \
                "warning" if response.status_code >= 400 else "info"

        record = {
            "ts": self._now(),
            "level": level,
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "duration_ms": duration_ms,
            "size_bytes": size_bytes,
            "client_ip": client_ip,
        }

        # Include query string if present
        if request.url.query:
            record["query"] = request.url.query

        self._log(record)

        # Increment Redis request counter (only for API endpoints, not static/ui)
        if not request.url.path.startswith("/static") and request.url.path not in ("/", "/ui", "/builder", "/docs", "/redoc", "/healthz", "/metrics"):
            reg.increment_request_counter()

        # Pass request_id back in response header for client-side tracing
        response.headers["x-request-id"] = request_id
        return response

    def _log(self, record: dict):
        print(json.dumps(record), flush=True)

    @staticmethod
    def _now() -> str:
        import datetime
        return datetime.datetime.utcnow().isoformat() + "Z"


def setup_logging():
    """Configure root logger to suppress uvicorn's default access log (we replace it)."""
    logging.basicConfig(level=logging.WARNING)
    # Suppress uvicorn access log — our middleware replaces it
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    # Keep uvicorn error log for startup errors
    logging.getLogger("uvicorn.error").setLevel(logging.INFO)
