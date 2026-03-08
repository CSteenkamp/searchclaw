"""Application configuration from environment variables."""

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings loaded from environment."""

    # App
    app_name: str = "SearchClaw"
    app_version: str = "0.1.0"
    debug: bool = False

    # Security
    api_key_hmac_secret: str = "change-me-in-production"

    # CORS
    cors_origins: list[str] = ["https://searchclaw.dev", "http://localhost:3000"]

    # Database
    database_url: str = "postgresql+asyncpg://searchclaw:searchclaw@localhost:5432/searchclaw"

    # Redis
    redis_url: str = "redis://localhost:6379/0"
    cache_ttl_web: int = 21600  # 6 hours
    cache_ttl_news: int = 3600  # 1 hour
    cache_ttl_images: int = 86400  # 24 hours
    cache_ttl_suggest: int = 86400  # 24 hours
    cache_ttl_extract: int = 3600  # 1 hour

    # SearXNG
    searxng_urls: list[str] = ["http://localhost:8888"]
    searxng_timeout: float = 10.0

    # Browser pool (spec 2)
    browser_pool_size: int = 3
    browser_timeout: int = 30000

    # LLM (spec 2)
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    llm_fallback_model: str = "claude-3-haiku-20240307"

    # Proxy (spec 7)
    proxy_datacenter_url: str = ""
    proxy_residential_url: str = ""
    proxy_auto_escalate: bool = True  # Auto-retry with proxy on 403

    # Rate limiting
    global_rate_limit: int = 10  # per second per IP (unauthenticated)
    default_rate_limit: int = 1  # per second (free tier)

    # Stripe
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_price_starter: str = ""  # Stripe Price ID for Starter plan
    stripe_price_pro: str = ""  # Stripe Price ID for Pro plan
    stripe_price_scale: str = ""  # Stripe Price ID for Scale plan
    stripe_price_metered: str = ""  # Stripe Price ID for metered overage billing
    stripe_meter_event_name: str = "searchclaw_query_usage"  # Stripe Meter event name

    # Cloudflare
    cf_api_token: str = ""
    cf_zone_id: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
