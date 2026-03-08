"""Tests for proxy rotation manager — api/services/proxy_manager.py."""

import time

import pytest
from unittest.mock import patch, MagicMock

from api.services.proxy_manager import (
    ProxyConfig,
    ProxyManager,
    resolve_proxy_tier,
    init_proxy_manager,
    get_proxy_manager,
)


# ── ProxyConfig ─────────────────────────────────────────────────────────


def test_proxy_config_defaults():
    p = ProxyConfig(url="http://proxy:8080", tier="datacenter")
    assert p.failures == 0
    assert p.last_failure == 0.0


# ── ProxyManager.get_proxy ──────────────────────────────────────────────


def _make_manager(dc=None, res=None):
    """Build a ProxyManager without reading settings."""
    with patch("api.services.proxy_manager.get_settings") as mock:
        s = MagicMock()
        s.proxy_datacenter_url = ""
        s.proxy_residential_url = ""
        mock.return_value = s
        mgr = ProxyManager()
    mgr.datacenter_proxies = dc or []
    mgr.residential_proxies = res or []
    return mgr


def test_get_proxy_none_tier():
    mgr = _make_manager(dc=[ProxyConfig(url="http://dc:1", tier="datacenter")])
    assert mgr.get_proxy("none") is None


def test_get_proxy_empty_pool():
    mgr = _make_manager()
    assert mgr.get_proxy("datacenter") is None
    assert mgr.get_proxy("residential") is None


def test_get_proxy_round_robin():
    proxies = [
        ProxyConfig(url="http://dc:1", tier="datacenter"),
        ProxyConfig(url="http://dc:2", tier="datacenter"),
    ]
    mgr = _make_manager(dc=proxies)

    first = mgr.get_proxy("datacenter")
    second = mgr.get_proxy("datacenter")
    assert first.url != second.url


def test_get_proxy_skips_failed():
    """Proxy with failures >= threshold is skipped during cooldown."""
    p1 = ProxyConfig(url="http://dc:1", tier="datacenter", failures=10, last_failure=time.monotonic())
    p2 = ProxyConfig(url="http://dc:2", tier="datacenter")
    mgr = _make_manager(dc=[p1, p2])

    result = mgr.get_proxy("datacenter")
    assert result.url == "http://dc:2"


def test_get_proxy_resets_after_cooldown():
    """Proxy recovers after cooldown expires."""
    p = ProxyConfig(url="http://dc:1", tier="datacenter", failures=10, last_failure=time.monotonic() - 120)
    mgr = _make_manager(dc=[p])
    mgr.cooldown_seconds = 60.0

    result = mgr.get_proxy("datacenter")
    assert result.url == "http://dc:1"
    assert result.failures == 0  # reset


def test_get_proxy_all_in_cooldown_returns_first():
    """When every proxy is in cooldown, return the first one."""
    now = time.monotonic()
    proxies = [
        ProxyConfig(url="http://dc:1", tier="datacenter", failures=10, last_failure=now),
        ProxyConfig(url="http://dc:2", tier="datacenter", failures=10, last_failure=now),
    ]
    mgr = _make_manager(dc=proxies)
    result = mgr.get_proxy("datacenter")
    assert result.url == "http://dc:1"


def test_get_proxy_residential():
    p = ProxyConfig(url="http://res:1", tier="residential")
    mgr = _make_manager(res=[p])
    result = mgr.get_proxy("residential")
    assert result.url == "http://res:1"


# ── report_failure ──────────────────────────────────────────────────────


def test_report_failure_increments():
    p = ProxyConfig(url="http://dc:1", tier="datacenter")
    mgr = _make_manager(dc=[p])
    mgr.report_failure(p)
    assert p.failures == 1
    assert p.last_failure > 0


# ── get_stats ───────────────────────────────────────────────────────────


def test_get_stats():
    mgr = _make_manager(
        dc=[ProxyConfig(url="http://dc:1", tier="datacenter")],
        res=[ProxyConfig(url="http://res:1", tier="residential")],
    )
    stats = mgr.get_stats()
    assert stats["datacenter"]["count"] == 1
    assert stats["residential"]["count"] == 1


# ── resolve_proxy_tier ──────────────────────────────────────────────────


def test_resolve_tier_explicit():
    assert resolve_proxy_tier("residential", "free") == "residential"
    assert resolve_proxy_tier("none", "pro") == "none"
    assert resolve_proxy_tier("datacenter", "free") == "datacenter"


def test_resolve_tier_default_free():
    assert resolve_proxy_tier(None, "free") == "none"


def test_resolve_tier_default_paid():
    assert resolve_proxy_tier(None, "pro") == "datacenter"
    assert resolve_proxy_tier(None, "starter") == "datacenter"
    assert resolve_proxy_tier(None, "scale") == "datacenter"
    assert resolve_proxy_tier(None, "enterprise") == "datacenter"


# ── init / get singleton ────────────────────────────────────────────────


def test_init_and_get_proxy_manager():
    with patch("api.services.proxy_manager.get_settings") as mock:
        s = MagicMock()
        s.proxy_datacenter_url = ""
        s.proxy_residential_url = ""
        mock.return_value = s
        mgr = init_proxy_manager()

    assert mgr is not None
    assert get_proxy_manager() is mgr
