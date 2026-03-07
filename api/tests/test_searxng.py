"""Tests for SearXNG client — retry logic, circuit breaker, and response parsing."""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock
import httpx

from api.services.searxng_client import (
    init_searxng_pool,
    execute_search,
    _pick_instance,
    _record_failure,
    _record_success,
    _failure_counts,
    _cooldown_until,
    _FAILURE_THRESHOLD,
)


@pytest.fixture(autouse=True)
def reset_pool():
    """Reset the SearXNG pool state between tests."""
    import api.services.searxng_client as mod
    mod._pool = []
    mod._client = None
    mod._failure_counts.clear()
    mod._cooldown_until.clear()
    yield


@pytest.fixture
def pool_with_client():
    """Initialize pool with 3 instances and a mock httpx client."""
    import api.services.searxng_client as mod
    urls = ["http://searxng-1:8080", "http://searxng-2:8080", "http://searxng-3:8080"]
    mod._pool = urls
    mod._client = AsyncMock(spec=httpx.AsyncClient)
    return urls, mod._client


def test_pick_instance_random(pool_with_client):
    urls, _ = pool_with_client
    picked = {_pick_instance() for _ in range(50)}
    # Should pick from available instances
    assert picked.issubset(set(urls))
    # With 50 tries across 3 instances, should hit at least 2
    assert len(picked) >= 2


def test_pick_instance_excludes(pool_with_client):
    urls, _ = pool_with_client
    picked = _pick_instance(exclude={urls[0], urls[1]})
    assert picked == urls[2]


def test_pick_instance_no_pool():
    import api.services.searxng_client as mod
    mod._pool = []
    with pytest.raises(RuntimeError, match="No SearXNG instances configured"):
        _pick_instance()


def test_circuit_breaker_cooldown(pool_with_client):
    urls, _ = pool_with_client

    # Trigger failures on instance 1
    for _ in range(_FAILURE_THRESHOLD):
        _record_failure(urls[0])

    # Instance 1 should be in cooldown
    assert urls[0] in _cooldown_until

    # Picking should avoid instance 1
    picks = {_pick_instance() for _ in range(30)}
    assert urls[0] not in picks


def test_circuit_breaker_recovery(pool_with_client):
    urls, _ = pool_with_client

    # Put instance 1 in cooldown
    for _ in range(_FAILURE_THRESHOLD):
        _record_failure(urls[0])
    assert urls[0] in _cooldown_until

    # Record success clears it
    _record_success(urls[0])
    assert urls[0] not in _cooldown_until
    assert _failure_counts[urls[0]] == 0


@pytest.mark.asyncio
async def test_execute_search_success(pool_with_client):
    urls, mock_client = pool_with_client

    # Mock successful SearXNG response
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "results": [
            {"title": "Result 1", "url": "https://example.com", "content": "Snippet 1", "engine": "google"},
        ],
        "infoboxes": [],
        "suggestions": ["suggestion 1"],
    }
    mock_client.get = AsyncMock(return_value=mock_resp)

    result = await execute_search(query="test")
    assert result["query"] == "test"
    assert len(result["results"]) == 1
    assert result["results"][0]["title"] == "Result 1"
    assert result["results"][0]["snippet"] == "Snippet 1"
    assert result["meta"]["cached"] is False
    assert "google" in result["meta"]["engines_used"]


@pytest.mark.asyncio
async def test_execute_search_retry_on_failure(pool_with_client):
    urls, mock_client = pool_with_client

    # First call fails, second succeeds
    fail_resp = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
    ok_resp = MagicMock()
    ok_resp.status_code = 200
    ok_resp.raise_for_status = MagicMock()
    ok_resp.json.return_value = {"results": [], "infoboxes": [], "suggestions": []}

    mock_client.get = AsyncMock(side_effect=[
        httpx.ConnectError("Connection refused"),
        ok_resp,
    ])

    result = await execute_search(query="retry test")
    assert result["query"] == "retry test"
    assert mock_client.get.call_count == 2


@pytest.mark.asyncio
async def test_execute_search_all_fail(pool_with_client):
    urls, mock_client = pool_with_client

    mock_client.get = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))

    with pytest.raises(RuntimeError, match="All SearXNG instances failed"):
        await execute_search(query="doomed query")

    # Should have tried all 3 instances
    assert mock_client.get.call_count == 3


@pytest.mark.asyncio
async def test_execute_search_not_initialized():
    import api.services.searxng_client as mod
    mod._pool = ["http://fake:8080"]
    mod._client = None

    with pytest.raises(RuntimeError, match="not initialized"):
        await execute_search(query="test")


@pytest.mark.asyncio
async def test_execute_search_parses_infobox(pool_with_client):
    urls, mock_client = pool_with_client

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "results": [],
        "infoboxes": [
            {"infobox": "Python", "content": "A programming language", "urls": [{"url": "https://python.org"}]},
        ],
        "suggestions": [],
    }
    mock_client.get = AsyncMock(return_value=mock_resp)

    result = await execute_search(query="python")
    assert result["infobox"]["title"] == "Python"
    assert result["infobox"]["content"] == "A programming language"
    assert result["infobox"]["url"] == "https://python.org"
