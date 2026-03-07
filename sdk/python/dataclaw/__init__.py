"""SearchClaw Python SDK — Cheap, fast search API for AI agents."""

from searchclaw.client import (
    AsyncSearchClaw,
    AuthError,
    RateLimitError,
    SearchClaw,
    SearchClawError,
)

__all__ = [
    "SearchClaw",
    "AsyncSearchClaw",
    "SearchClawError",
    "AuthError",
    "RateLimitError",
]

__version__ = "0.1.0"
