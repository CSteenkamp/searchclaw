"""Shared test fixtures for DataClaw API tests."""

import asyncio
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient, ASGITransport

from api.main import app
from api.middleware.auth import get_api_key_user
from api.services import cache as cache_module
from api.services import searxng_client as searxng_module


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def client():
    """Async HTTP client for testing the FastAPI app."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def mock_redis():
    """Mock Redis so tests don't need a real Redis instance."""
    store = {}
    counters = {}

    async def fake_get_cached(key):
        return store.get(f"dc:{key}")

    async def fake_set_cached(key, value, ttl=21600):
        store[f"dc:{key}"] = value

    async def fake_get_counter(key):
        return counters.get(key, 0)

    async def fake_incr_counter(key, amount=1, ttl=86400):
        counters[key] = counters.get(key, 0) + amount
        return counters[key]

    async def fake_decr_counter(key, amount=1):
        counters[key] = counters.get(key, 0) - amount
        return counters[key]

    async def fake_ping():
        return True

    with patch.object(cache_module, "get_cached", side_effect=fake_get_cached), \
         patch.object(cache_module, "set_cached", side_effect=fake_set_cached), \
         patch.object(cache_module, "get_counter", side_effect=fake_get_counter), \
         patch.object(cache_module, "incr_counter", side_effect=fake_incr_counter), \
         patch.object(cache_module, "decr_counter", side_effect=fake_decr_counter), \
         patch.object(cache_module, "ping_cache", side_effect=fake_ping), \
         patch("api.routers.search.get_cached", side_effect=fake_get_cached), \
         patch("api.routers.search.set_cached", side_effect=fake_set_cached), \
         patch("api.middleware.rate_limit.incr_counter", side_effect=fake_incr_counter), \
         patch("api.middleware.rate_limit.decr_counter", side_effect=fake_decr_counter), \
         patch("api.middleware.auth.get_cached", side_effect=fake_get_cached), \
         patch("api.middleware.auth.set_cached", side_effect=fake_set_cached), \
         patch("api.middleware.auth.get_counter", side_effect=fake_get_counter), \
         patch("api.middleware.auth.incr_counter", side_effect=fake_incr_counter), \
         patch("api.middleware.rate_limit.record_usage_to_db", new_callable=AsyncMock):
        yield {"store": store, "counters": counters}


@pytest.fixture
def mock_searxng():
    """Mock SearXNG client to return fake search results."""
    fake_results = {
        "query": "test query",
        "results": [
            {
                "title": "Test Result 1",
                "url": "https://example.com/1",
                "snippet": "This is test result 1",
                "source": "google",
                "position": 1,
            },
            {
                "title": "Test Result 2",
                "url": "https://example.com/2",
                "snippet": "This is test result 2",
                "source": "bing",
                "position": 2,
            },
        ],
        "infobox": None,
        "suggestions": ["test suggestion"],
        "meta": {
            "total_results": 2,
            "cached": False,
            "response_time_ms": 150,
            "engines_used": ["google", "bing"],
        },
    }

    with patch("api.routers.search.execute_search", new_callable=AsyncMock) as mock:
        mock.return_value = fake_results
        yield mock


@pytest.fixture
def mock_db_user():
    """Mock the auth dependency to return a fake authenticated user."""
    user_info = {
        "user_id": 1,
        "api_key_id": 1,
        "plan": "pro",
        "rate_per_sec": 20,
        "monthly_credits": 100000,
        "email": "test@example.com",
    }

    async def override():
        return user_info

    app.dependency_overrides[get_api_key_user] = override
    yield user_info
    app.dependency_overrides.pop(get_api_key_user, None)


@pytest.fixture
def free_user():
    """Mock user on free plan."""
    user_info = {
        "user_id": 2,
        "api_key_id": 2,
        "plan": "free",
        "rate_per_sec": 1,
        "monthly_credits": 1000,
        "email": "free@example.com",
    }

    async def override():
        return user_info

    app.dependency_overrides[get_api_key_user] = override
    yield user_info
    app.dependency_overrides.pop(get_api_key_user, None)
