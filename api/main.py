"""DataClaw API — Search, Extract, Crawl — One API for AI agents."""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.config import get_settings
from api.routers import search, health, billing, auth
from api.middleware.metrics import setup_metrics


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

    # Placeholder: browser pool init (spec 2)
    # Placeholder: worker registration (spec 2)

    yield

    # Shutdown
    from api.services.cache import close_cache
    from api.services.database import close_db

    await close_cache()
    await close_db()


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="Search, Extract, Crawl — One API for AI agents. $1/1K credits.",
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

    # Prometheus metrics
    setup_metrics(app)

    return app


app = create_app()
