"""Health check endpoints."""

from fastapi import APIRouter
from datetime import datetime, timezone

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz():
    """Kubernetes liveness probe."""
    return {"status": "ok"}


@router.get("/readyz")
async def readyz():
    """Kubernetes readiness probe. Checks Redis + PostgreSQL + SearXNG + Browser pool."""
    checks = {}

    # Check Redis
    try:
        from api.services.cache import ping_cache

        checks["redis"] = await ping_cache()
    except Exception:
        checks["redis"] = False

    # Check PostgreSQL
    try:
        from api.services.database import ping_db

        checks["postgres"] = await ping_db()
    except Exception:
        checks["postgres"] = False

    # Check SearXNG
    try:
        from api.services.searxng_client import ping_searxng

        checks["searxng"] = await ping_searxng()
    except Exception:
        checks["searxng"] = False

    # Browser pool status (placeholder — will be wired in spec 2)
    checks["browser_pool"] = True

    all_ok = all(checks.values())
    return {
        "status": "ok" if all_ok else "degraded",
        "checks": checks,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/")
async def root():
    """API root — basic info."""
    from api.config import get_settings

    settings = get_settings()
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "docs": "/docs",
        "api": "/v1/search",
    }
