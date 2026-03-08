"""SearchClaw API — Search, Extract, Crawl — One API for AI agents."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse

from api.config import get_settings
from api.routers import search, health, billing, auth, extract, markdown, screenshot, crawl, jobs, pipeline, map as map_router_mod, browse
from api.middleware.metrics import setup_metrics

tags_metadata = [
    {"name": "Search", "description": "Web, news, and image search via SearXNG."},
    {"name": "Extract", "description": "Schema-driven structured data extraction from URLs."},
    {"name": "Crawl", "description": "Async multi-page crawl and extraction jobs."},
    {"name": "Pipeline", "description": "Search + extract in a single call."},
    {"name": "Auth", "description": "API key management and registration."},
    {"name": "Billing", "description": "Subscription management and Stripe integration."},
    {"name": "Health", "description": "Liveness, readiness, and status probes."},
    {"name": "Map", "description": "URL discovery via sitemap + BFS crawl."},
    {"name": "Browse", "description": "Interactive browser actions — click, type, scroll, extract."},
    {"name": "Agent", "description": "Autonomous data gathering from natural language prompts."},
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    settings = get_settings()

    # Init services
    from api.services.cache import init_cache
    from api.services.searxng_client import init_searxng_pool
    from api.services.database import init_db

    await init_cache(settings.redis_url)
    await init_db(settings.database_url)
    init_searxng_pool(settings.searxng_urls)

    # Browser pool init (spec 2)
    from api.services.browser_pool import init_browser_pool, close_browser_pool
    try:
        await init_browser_pool()
    except Exception:
        import logging
        logging.getLogger(__name__).warning("Browser pool failed to start — extraction endpoints unavailable")

    yield

    # Shutdown
    from api.services.cache import close_cache
    from api.services.database import close_db
    from api.services.browser_pool import close_browser_pool as _close_pool

    try:
        await _close_pool()
    except Exception:
        pass
    await close_cache()
    await close_db()


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="SearchClaw API",
        description="Search, Extract, Crawl — One API. The complete web data pipeline for AI agents.",
        version="1.0.0",
        terms_of_service="https://searchclaw.dev/terms",
        contact={"name": "SearchClaw Support", "email": "support@searchclaw.dev"},
        license_info={"name": "Proprietary"},
        servers=[
            {"url": "https://api.searchclaw.dev", "description": "Production"},
            {"url": "http://localhost:8000", "description": "Local development"},
        ],
        openapi_tags=tags_metadata,
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["X-API-Key", "Authorization", "Content-Type"],
    )

    # Routers
    app.include_router(health.router)
    app.include_router(search.router, prefix="/v1")
    app.include_router(billing.router, prefix="/v1")
    app.include_router(auth.router, prefix="/v1")
    app.include_router(extract.router, prefix="/v1")
    app.include_router(markdown.router, prefix="/v1")
    app.include_router(screenshot.router, prefix="/v1")
    app.include_router(crawl.router, prefix="/v1")
    app.include_router(jobs.router, prefix="/v1")
    app.include_router(pipeline.router, prefix="/v1")
    app.include_router(map_router_mod.router, prefix="/v1")
    app.include_router(browse.router, prefix="/v1")

    # Prometheus metrics
    setup_metrics(app)

    # llms.txt routes for AI agent discovery
    _dashboard_dir = Path(__file__).resolve().parent.parent / "dashboard"

    @app.get("/llms.txt", response_class=PlainTextResponse, include_in_schema=False)
    async def serve_llms_txt():
        """Serve llms.txt for AI agent discovery."""
        return (_dashboard_dir / "llms.txt").read_text()

    @app.get("/llms-full.txt", response_class=PlainTextResponse, include_in_schema=False)
    async def serve_llms_full_txt():
        """Serve expanded llms-full.txt for AI agent discovery."""
        return (_dashboard_dir / "llms-full.txt").read_text()

    # Serve dashboard static files (must be last — catch-all mount)
    if _dashboard_dir.is_dir():
        from fastapi.staticfiles import StaticFiles
        app.mount("/", StaticFiles(directory=str(_dashboard_dir), html=True), name="dashboard")

    return app


app = create_app()
