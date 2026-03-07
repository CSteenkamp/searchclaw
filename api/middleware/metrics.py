"""Prometheus metrics and raw ASGI middleware for DataClaw API."""

import time

from fastapi import FastAPI
from prometheus_client import (
    Counter,
    Gauge,
    Histogram,
    generate_latest,
    CONTENT_TYPE_LATEST,
)
from starlette.responses import Response as StarletteResponse


# --- Metrics ---

REQUEST_COUNT = Counter(
    "dataclaw_requests_total",
    "Total API requests",
    ["endpoint", "status_code"],
)

RESPONSE_TIME = Histogram(
    "dataclaw_response_time_seconds",
    "Response time in seconds",
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

CACHE_HITS = Counter(
    "dataclaw_cache_hits_total",
    "Total cache hits",
)

CACHE_REQUESTS = Counter(
    "dataclaw_cache_requests_total",
    "Total cache-eligible requests",
)

SEARXNG_ERRORS = Counter(
    "dataclaw_searxng_errors_total",
    "Total SearXNG errors",
    ["instance", "engine"],
)

ACTIVE_USERS = Gauge(
    "dataclaw_active_users",
    "Currently active unique users (API keys) in the last 5 minutes",
)

CREDITS_CONSUMED = Counter(
    "dataclaw_credits_consumed_total",
    "Total credits consumed",
)


# --- Raw ASGI Middleware (replaces BaseHTTPMiddleware to avoid streaming issues) ---

class MetricsMiddleware:
    """Collect request metrics using raw ASGI protocol."""

    def __init__(self, app, **kwargs):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"] == "/metrics":
            await self.app(scope, receive, send)
            return

        start_time = time.perf_counter()
        status_code = 500

        async def send_wrapper(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration = time.perf_counter() - start_time
            REQUEST_COUNT.labels(
                endpoint=scope["path"],
                status_code=str(status_code),
            ).inc()
            RESPONSE_TIME.observe(duration)


# --- Setup ---

def setup_metrics(app: FastAPI) -> None:
    """Add metrics middleware and /metrics endpoint."""
    app.add_middleware(MetricsMiddleware)

    @app.get("/metrics", include_in_schema=False)
    async def metrics_endpoint():
        return StarletteResponse(
            content=generate_latest(),
            media_type=CONTENT_TYPE_LATEST,
        )
