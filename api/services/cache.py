"""Redis caching layer."""

import json
import redis.asyncio as redis
from typing import Optional

_redis: Optional[redis.Redis] = None


async def init_cache(redis_url: str):
    """Initialize Redis connection."""
    global _redis
    _redis = redis.from_url(redis_url, decode_responses=True)


async def close_cache():
    """Close Redis connection."""
    global _redis
    if _redis:
        await _redis.close()
        _redis = None


async def ping_cache() -> bool:
    """Check Redis connectivity."""
    if not _redis:
        return False
    try:
        return await _redis.ping()
    except Exception:
        return False


async def get_cached(key: str) -> Optional[dict]:
    """Get a cached JSON response by key (dc: prefixed)."""
    if not _redis:
        return None
    try:
        data = await _redis.get(f"dc:{key}")
        if data:
            return json.loads(data)
    except Exception:
        pass
    return None


async def set_cached(key: str, value: dict, ttl: int = 21600):
    """Cache a JSON response with TTL (dc: prefixed)."""
    if not _redis:
        return
    try:
        await _redis.setex(f"dc:{key}", ttl, json.dumps(value))
    except Exception:
        pass


async def get_counter(key: str) -> int:
    """Get a raw counter value (no prefix, no JSON parsing)."""
    if not _redis:
        return 0
    try:
        val = await _redis.get(key)
        return int(val) if val else 0
    except Exception:
        return 0


async def incr_counter(key: str, amount: int = 1, ttl: int = 86400) -> int:
    """Atomically increment a counter. Sets TTL only on first creation."""
    if not _redis:
        return 0
    val = await _redis.incrby(key, amount)
    if val == amount:
        await _redis.expire(key, ttl)
    return val


async def decr_counter(key: str, amount: int = 1) -> int:
    """Decrement a counter (for releasing reserved credits on failure)."""
    if not _redis:
        return 0
    return await _redis.decrby(key, amount)


def get_redis_client():
    """Get the raw Redis client for direct operations (e.g., job tracking)."""
    return _redis
