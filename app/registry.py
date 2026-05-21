"""
Schema registry backed by Redis.

Falls back to in-memory storage if Redis is unavailable, so the service
remains functional even if Redis is down — schemas just won't persist
across restarts or be shared between replicas in that case.
"""

import json
import logging
import os
import uuid
from typing import Any, Optional

import redis

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration — injected via environment variables from K8s Secret
# ---------------------------------------------------------------------------

REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "")
REDIS_DB = int(os.getenv("REDIS_DB", "0"))
REDIS_KEY_PREFIX = "schema-validator:schema:"
REDIS_TTL = None  # No expiry — schemas persist until explicitly deleted

# Maximum number of schemas allowed in the registry
# Prevents unbounded growth from abuse or runaway automation
MAX_REGISTRY_SIZE = int(os.getenv("MAX_REGISTRY_SIZE", "1000"))


# ---------------------------------------------------------------------------
# Redis client (lazy init)
# ---------------------------------------------------------------------------

_redis_client: Optional[redis.Redis] = None
_redis_available: bool = False


def _get_redis() -> Optional[redis.Redis]:
    global _redis_client, _redis_available
    if _redis_client is None:
        try:
            _redis_client = redis.Redis(
                host=REDIS_HOST,
                port=REDIS_PORT,
                password=REDIS_PASSWORD or None,
                db=REDIS_DB,
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=2,
            )
            _redis_client.ping()
            _redis_available = True
            logger.info(f"Connected to Redis at {REDIS_HOST}:{REDIS_PORT}")
        except Exception as e:
            _redis_available = False
            _redis_client = None
            logger.warning(f"Redis unavailable ({e}) — falling back to in-memory registry")
    return _redis_client if _redis_available else None


def _redis_key(schema_id: str) -> str:
    return f"{REDIS_KEY_PREFIX}{schema_id}"


# ---------------------------------------------------------------------------
# In-memory fallback
# ---------------------------------------------------------------------------

_memory_store: dict[str, dict] = {}


# ---------------------------------------------------------------------------
# Public registry API
# ---------------------------------------------------------------------------

def register_schema(format: str, schema_def: Any, description: Optional[str] = None) -> str:
    """
    Store a schema and return its ID.
    Raises ValueError if the registry cap has been reached.
    """
    # Enforce registry size cap
    current = list_schemas()
    if len(current) >= MAX_REGISTRY_SIZE:
        raise ValueError(f"Registry cap reached ({MAX_REGISTRY_SIZE} schemas). Delete unused schemas before registering new ones.")

    schema_id = str(uuid.uuid4())
    entry = {
        "format": format,
        "schema": schema_def,
        "description": description,
    }

    r = _get_redis()
    if r:
        try:
            r.set(_redis_key(schema_id), json.dumps(entry))
            return schema_id
        except Exception as e:
            logger.warning(f"Redis write failed ({e}) — falling back to memory")

    _memory_store[schema_id] = entry
    return schema_id


def get_schema(schema_id: str) -> Optional[dict]:
    """Retrieve a schema entry by ID. Returns None if not found."""
    r = _get_redis()
    if r:
        try:
            raw = r.get(_redis_key(schema_id))
            if raw:
                return json.loads(raw)
            return None
        except Exception as e:
            logger.warning(f"Redis read failed ({e}) — falling back to memory")

    return _memory_store.get(schema_id)


def list_schemas() -> list[dict]:
    """Return a summary list of all registered schemas."""
    r = _get_redis()
    if r:
        try:
            keys = r.keys(f"{REDIS_KEY_PREFIX}*")
            results = []
            for key in keys:
                raw = r.get(key)
                if raw:
                    entry = json.loads(raw)
                    schema_id = key.removeprefix(REDIS_KEY_PREFIX)
                    results.append({
                        "schema_id": schema_id,
                        "format": entry["format"],
                        "description": entry.get("description"),
                    })
            return results
        except Exception as e:
            logger.warning(f"Redis list failed ({e}) — falling back to memory")

    return [
        {
            "schema_id": sid,
            "format": entry["format"],
            "description": entry.get("description"),
        }
        for sid, entry in _memory_store.items()
    ]


def delete_schema(schema_id: str) -> bool:
    """Delete a schema by ID. Returns True if deleted, False if not found."""
    r = _get_redis()
    if r:
        try:
            deleted = r.delete(_redis_key(schema_id))
            return deleted > 0
        except Exception as e:
            logger.warning(f"Redis delete failed ({e}) — falling back to memory")

    if schema_id in _memory_store:
        del _memory_store[schema_id]
        return True
    return False


def registry_status() -> dict:
    """Return backend status — useful for healthz."""
    r = _get_redis()
    if r:
        try:
            r.ping()
            return {"backend": "redis", "host": REDIS_HOST, "port": REDIS_PORT, "available": True}
        except Exception:
            pass
    return {"backend": "memory", "available": True, "warning": "Redis unavailable — schemas are not persistent"}


# ---------------------------------------------------------------------------
# Request counter — tracks API calls per day using Redis INCR + expiry
# Keys: schema-validator:requests:YYYY-MM-DD
# ---------------------------------------------------------------------------

COUNTER_KEY_PREFIX = "schema-validator:requests:"


def increment_request_counter():
    """Increment today's request counter. Silently fails if Redis is unavailable."""
    import datetime
    r = _get_redis()
    if not r:
        return
    try:
        key = f"{COUNTER_KEY_PREFIX}{datetime.date.today().isoformat()}"
        pipe = r.pipeline()
        pipe.incr(key)
        pipe.expire(key, 60 * 60 * 48)  # keep for 48 hours
        pipe.execute()
    except Exception:
        pass


def get_requests_last_24h() -> int:
    """Return total API requests in the last 24 hours. Returns 0 if unavailable."""
    import datetime
    r = _get_redis()
    if not r:
        return 0
    try:
        today = datetime.date.today().isoformat()
        yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
        keys = [
            f"{COUNTER_KEY_PREFIX}{today}",
            f"{COUNTER_KEY_PREFIX}{yesterday}",
        ]
        values = r.mget(keys)
        return sum(int(v) for v in values if v)
    except Exception:
        return 0
