"""SearchClaw Python SDK — Search, Extract, Crawl — One API."""

from searchclaw.client import (
    AsyncSearchClaw,
    AuthError,
    SearchClaw,
    SearchClawError,
    RateLimitError,
)

__all__ = [
    "SearchClaw",
    "AsyncSearchClaw",
    "SearchClawError",
    "AuthError",
    "RateLimitError",
]

__version__ = "0.2.0"
