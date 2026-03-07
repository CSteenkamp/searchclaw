"""SearXNG instance pool with retry logic and circuit breaker."""

import httpx
import time
import random
from typing import Optional
from collections import defaultdict

from api.middleware.metrics import SEARXNG_ERRORS

_pool: list[str] = []
_client: Optional[httpx.AsyncClient] = None

# Circuit breaker state
_failure_counts: dict[str, int] = defaultdict(int)
_cooldown_until: dict[str, float] = {}

_FAILURE_THRESHOLD = 3
_COOLDOWN_SECONDS = 30
_MAX_RETRIES = 3


def init_searxng_pool(urls: list[str]):
    """Initialize the SearXNG instance pool."""
    global _pool, _client
    _pool = urls
    _client = httpx.AsyncClient(
        timeout=10.0,
        limits=httpx.Limits(max_connections=200, max_keepalive_connections=50),
    )


async def ping_searxng() -> bool:
    """Check if at least one SearXNG instance is reachable."""
    if not _pool or not _client:
        return False
    for url in _pool:
        try:
            resp = await _client.get(f"{url}/healthz", timeout=3.0)
            if resp.status_code == 200:
                return True
        except Exception:
            continue
    return False


def _pick_instance(exclude: set[str] | None = None) -> str:
    """Pick a healthy SearXNG instance, avoiding excluded and cooled-down ones."""
    now = time.monotonic()
    exclude = exclude or set()

    # Prefer healthy, non-excluded instances
    candidates = [
        url for url in _pool
        if url not in exclude and now > _cooldown_until.get(url, 0)
    ]
    # Fall back to non-excluded (even if in cooldown)
    if not candidates:
        candidates = [url for url in _pool if url not in exclude]
    # Last resort: any instance
    if not candidates:
        candidates = list(_pool)
    if not candidates:
        raise RuntimeError("No SearXNG instances configured")

    return random.choice(candidates)


def _record_failure(url: str):
    """Track instance failure; put in cooldown after threshold."""
    _failure_counts[url] += 1
    if _failure_counts[url] >= _FAILURE_THRESHOLD:
        _cooldown_until[url] = time.monotonic() + _COOLDOWN_SECONDS
        _failure_counts[url] = 0


def _record_success(url: str):
    """Clear failure state for a healthy instance."""
    _failure_counts[url] = 0
    _cooldown_until.pop(url, None)


async def execute_search(
    query: str,
    categories: list[str] | None = None,
    count: int = 10,
    offset: int = 0,
    language: str = "en",
    safesearch: int = 1,
    time_range: Optional[str] = None,
) -> dict:
    """Execute a search with automatic retry across SearXNG instances."""
    if not _client:
        raise RuntimeError("SearXNG client not initialized")

    attempts = min(len(_pool), _MAX_RETRIES) if _pool else 1
    tried: set[str] = set()
    last_error: Exception | None = None

    for _ in range(attempts):
        instance = _pick_instance(exclude=tried)
        tried.add(instance)
        start = time.monotonic()

        params = {
            "q": query,
            "format": "json",
            "language": language,
            "safesearch": safesearch,
            "pageno": (offset // max(count, 1)) + 1,
        }
        if categories:
            params["categories"] = ",".join(categories)
        if time_range:
            params["time_range"] = time_range

        try:
            resp = await _client.get(f"{instance}/search", params=params)
            resp.raise_for_status()
            data = resp.json()
            _record_success(instance)
        except Exception as e:
            _record_failure(instance)
            SEARXNG_ERRORS.labels(instance=instance, engine="all").inc()
            last_error = e
            continue

        elapsed_ms = int((time.monotonic() - start) * 1000)

        # Parse SearXNG response into our format
        results = []
        for i, r in enumerate(data.get("results", [])[:count]):
            results.append(
                {
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "snippet": r.get("content", ""),
                    "source": r.get("engine", ""),
                    "position": i + 1,
                }
            )

        # Infobox
        infobox = None
        infoboxes = data.get("infoboxes", [])
        if infoboxes:
            ib = infoboxes[0]
            infobox = {
                "title": ib.get("infobox", ""),
                "content": ib.get("content", ""),
                "url": (ib.get("urls", [{}])[0].get("url", "") if ib.get("urls") else ""),
            }

        suggestions = data.get("suggestions", [])[:10]
        engines_used = list(
            {r.get("engine", "") for r in data.get("results", []) if r.get("engine")}
        )

        return {
            "query": query,
            "results": results,
            "infobox": infobox,
            "suggestions": suggestions,
            "meta": {
                "total_results": len(results),
                "cached": False,
                "response_time_ms": elapsed_ms,
                "engines_used": engines_used,
            },
        }

    raise RuntimeError(f"All SearXNG instances failed after {attempts} attempts: {last_error}")
