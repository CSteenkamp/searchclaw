"""Tests for rate limiting and credit reservation logic."""

import pytest
from unittest.mock import patch
from fastapi import HTTPException

from api.middleware import rate_limit as rl_module
from api.middleware.rate_limit import check_rate_limit, reserve_credits, release_credits


@pytest.fixture
def pro_user():
    return {
        "user_id": 1,
        "api_key_id": 1,
        "plan": "pro",
        "rate_per_sec": 20,
        "monthly_credits": 100,
        "email": "test@example.com",
    }


@pytest.fixture
def counters():
    """Shared counter state for mock Redis."""
    return {}


@pytest.fixture(autouse=True)
def mock_cache(counters):
    async def fake_incr(key, amount=1, ttl=86400):
        counters[key] = counters.get(key, 0) + amount
        return counters[key]

    async def fake_decr(key, amount=1):
        counters[key] = counters.get(key, 0) - amount
        return counters[key]

    with patch.object(rl_module, "incr_counter", side_effect=fake_incr), \
         patch.object(rl_module, "decr_counter", side_effect=fake_decr):
        yield


@pytest.mark.asyncio
async def test_rate_limit_passes(pro_user):
    headers = await check_rate_limit(pro_user)
    assert headers["X-RateLimit-Limit"] == "20"
    assert int(headers["X-RateLimit-Remaining"]) >= 0


@pytest.mark.asyncio
async def test_rate_limit_exceeded(pro_user):
    # Use up the rate limit
    for _ in range(20):
        await check_rate_limit(pro_user)

    with pytest.raises(HTTPException) as exc_info:
        await check_rate_limit(pro_user)
    assert exc_info.value.status_code == 429
    assert "Rate limit" in exc_info.value.detail


@pytest.mark.asyncio
async def test_reserve_credits_success(pro_user):
    headers = await reserve_credits(pro_user, credits=1)
    assert headers["X-Credits-Used"] == "1"
    assert headers["X-Credits-Remaining"] == "99"


@pytest.mark.asyncio
async def test_reserve_credits_multiple(pro_user):
    await reserve_credits(pro_user, credits=1)
    headers = await reserve_credits(pro_user, credits=2)
    assert headers["X-Credits-Used"] == "3"
    assert headers["X-Credits-Remaining"] == "97"


@pytest.mark.asyncio
async def test_reserve_credits_at_limit(pro_user):
    await reserve_credits(pro_user, credits=100)

    with pytest.raises(HTTPException) as exc_info:
        await reserve_credits(pro_user, credits=1)
    assert exc_info.value.status_code == 429
    assert "Monthly credit limit" in exc_info.value.detail


@pytest.mark.asyncio
async def test_reserve_credits_rollback_on_exceed(pro_user, counters):
    """Credits should be rolled back if reservation exceeds the limit."""
    await reserve_credits(pro_user, credits=99)

    with pytest.raises(HTTPException):
        await reserve_credits(pro_user, credits=5)

    # Counter should be back to 99, not 104
    month_keys = [k for k in counters if k.startswith("usage:")]
    assert len(month_keys) == 1
    assert counters[month_keys[0]] == 99


@pytest.mark.asyncio
async def test_release_credits(pro_user, counters):
    await reserve_credits(pro_user, credits=10)

    month_keys = [k for k in counters if k.startswith("usage:")]
    assert counters[month_keys[0]] == 10

    await release_credits(pro_user, credits=10)
    assert counters[month_keys[0]] == 0


@pytest.mark.asyncio
async def test_concurrent_reservations_atomic(pro_user):
    """Simulate concurrent reservations — each INCR is atomic so totals stay correct."""
    import asyncio

    tasks = [reserve_credits(pro_user, credits=1) for _ in range(50)]
    results = await asyncio.gather(*tasks)
    assert len(results) == 50

    # Next 60 — only 50 should succeed (to reach 100 total)
    tasks2 = [reserve_credits(pro_user, credits=1) for _ in range(60)]
    results2 = await asyncio.gather(*tasks2, return_exceptions=True)

    successes = [r for r in results2 if not isinstance(r, Exception)]
    failures = [r for r in results2 if isinstance(r, Exception)]

    assert len(successes) == 50
    assert len(failures) == 10
