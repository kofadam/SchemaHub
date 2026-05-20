"""
Size limit middleware.

Two layers of protection:
1. HTTP body size limit — rejects requests larger than MAX_BODY_BYTES before parsing
2. Field-level size check — validates `data` and `schema_inline` field sizes
   (enforced in the validate and generate-schema endpoints via a dependency)
"""

import json
import os

from fastapi import HTTPException, Request, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from starlette.types import ASGIApp

# ---------------------------------------------------------------------------
# Limits — configurable via environment variables
# ---------------------------------------------------------------------------

# Maximum HTTP request body size (default 5MB)
MAX_BODY_BYTES = int(os.getenv("MAX_BODY_BYTES", str(5 * 1024 * 1024)))

# Maximum size of the `data` field (the actual content to validate, default 1MB)
MAX_DATA_BYTES = int(os.getenv("MAX_DATA_BYTES", str(1 * 1024 * 1024)))

# Maximum size of `schema_inline` (default 256KB)
MAX_SCHEMA_BYTES = int(os.getenv("MAX_SCHEMA_BYTES", str(256 * 1024)))


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    """
    Rejects requests whose body exceeds MAX_BODY_BYTES with HTTP 413.
    Checked before FastAPI parses the body.
    """

    def __init__(self, app: ASGIApp, max_bytes: int = MAX_BODY_BYTES):
        super().__init__(app)
        self.max_bytes = max_bytes

    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > self.max_bytes:
            return JSONResponse(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                content={
                    "detail": (
                        f"Request body too large. "
                        f"Maximum allowed size is {self.max_bytes // 1024}KB."
                    )
                },
            )
        return await call_next(request)


def check_field_sizes(data: str = None, schema_inline=None):
    """
    FastAPI dependency — call in endpoints that accept `data` and `schema_inline`.
    Raises HTTP 413 if either field exceeds its limit.
    """
    if data is not None:
        size = len(data.encode("utf-8"))
        if size > MAX_DATA_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=(
                    f"'data' field too large ({size // 1024}KB). "
                    f"Maximum allowed size is {MAX_DATA_BYTES // 1024}KB."
                ),
            )

    if schema_inline is not None:
        try:
            schema_str = json.dumps(schema_inline) if not isinstance(schema_inline, str) else schema_inline
            size = len(schema_str.encode("utf-8"))
            if size > MAX_SCHEMA_BYTES:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail=(
                        f"'schema_inline' field too large ({size // 1024}KB). "
                        f"Maximum allowed size is {MAX_SCHEMA_BYTES // 1024}KB."
                    ),
                )
        except (TypeError, ValueError):
            pass  # Let the validator handle malformed schema
