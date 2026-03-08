"""Proxy rotation manager — manages datacenter and residential proxy pools."""

import logging
import time
from dataclasses import dataclass, field
from typing import Literal

from api.config import get_settings

logger = logging.getLogger(__name__)

ProxyTier = Literal["none", "datacenter", "residential"]


@dataclass
class ProxyConfig:
    """A single proxy configuration."""
    url: str
    tier: ProxyTier
    failures: int = 0
    last_failure: float = 0.0


@dataclass
class ProxyManager:
    """Manages proxy pools with failure tracking and tier selection."""

    datacenter_proxies: list[ProxyConfig] = field(default_factory=list)
    residential_proxies: list[ProxyConfig] = field(default_factory=list)
    _dc_index: int = 0
    _res_index: int = 0
    failure_threshold: int = 5
    cooldown_seconds: float = 60.0

    def __post_init__(self):
        settings = get_settings()
        if settings.proxy_datacenter_url:
            for url in settings.proxy_datacenter_url.split(","):
                url = url.strip()
                if url:
                    self.datacenter_proxies.append(ProxyConfig(url=url, tier="datacenter"))
        if settings.proxy_residential_url:
            for url in settings.proxy_residential_url.split(","):
                url = url.strip()
                if url:
                    self.residential_proxies.append(ProxyConfig(url=url, tier="residential"))

    def get_proxy(self, tier: ProxyTier = "datacenter") -> ProxyConfig | None:
        """Get a proxy for the given tier. Returns None for 'none' tier or if no proxies configured."""
        if tier == "none":
            return None

        pool = self.datacenter_proxies if tier == "datacenter" else self.residential_proxies
        if not pool:
            return None

        now = time.monotonic()
        # Round-robin with failure skip
        attempts = len(pool)
        idx_attr = "_dc_index" if tier == "datacenter" else "_res_index"

        for _ in range(attempts):
            idx = getattr(self, idx_attr) % len(pool)
            setattr(self, idx_attr, idx + 1)
            proxy = pool[idx]

            if proxy.failures >= self.failure_threshold:
                if now - proxy.last_failure < self.cooldown_seconds:
                    continue
                # Reset after cooldown
                proxy.failures = 0

            return proxy

        # All proxies in cooldown — return first anyway
        return pool[0] if pool else None

    def report_failure(self, proxy: ProxyConfig) -> None:
        """Track a proxy failure."""
        proxy.failures += 1
        proxy.last_failure = time.monotonic()
        logger.warning("Proxy failure: %s (failures=%d)", proxy.url, proxy.failures)

    def get_stats(self) -> dict:
        """Return proxy health metrics."""
        return {
            "datacenter": {
                "count": len(self.datacenter_proxies),
                "proxies": [
                    {"url": p.url[:30] + "...", "failures": p.failures}
                    for p in self.datacenter_proxies
                ],
            },
            "residential": {
                "count": len(self.residential_proxies),
                "proxies": [
                    {"url": p.url[:30] + "...", "failures": p.failures}
                    for p in self.residential_proxies
                ],
            },
        }


# Module-level singleton
_manager: ProxyManager | None = None


def init_proxy_manager() -> ProxyManager:
    """Initialize the global proxy manager."""
    global _manager
    _manager = ProxyManager()
    logger.info(
        "Proxy manager initialized: %d datacenter, %d residential",
        len(_manager.datacenter_proxies),
        len(_manager.residential_proxies),
    )
    return _manager


def get_proxy_manager() -> ProxyManager | None:
    """Get the global proxy manager instance."""
    return _manager


def resolve_proxy_tier(requested: ProxyTier | None, plan: str) -> ProxyTier:
    """Resolve the effective proxy tier based on request and plan.

    - Free plan defaults to 'none'
    - Paid plans default to 'datacenter'
    - 'residential' is always explicit opt-in
    """
    if requested is not None:
        return requested
    if plan in ("starter", "pro", "scale", "enterprise"):
        return "datacenter"
    return "none"
