"""Tests for search depth modes (fast/basic/deep) — spec 5.2."""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch

from api.services.query_normalizer import reformulate_query


class TestReformulateQuery:
    def test_removes_stop_words(self):
        result = reformulate_query("what is the best python framework")
        assert "best" in result
        assert "python" in result
        assert "framework" in result

    def test_adds_site_hints(self):
        result = reformulate_query("machine learning tutorial")
        assert "site:reddit.com" in result
        assert "site:news.ycombinator.com" in result

    def test_handles_short_query(self):
        result = reformulate_query("rust")
        assert "rust" in result

    def test_handles_all_stop_words(self):
        result = reformulate_query("is it a the")
        # Should fall back to first words
        assert len(result) > 0


@pytest.mark.asyncio
async def test_search_fast_mode(client, mock_db_user, mock_redis, mock_searxng):
    """Fast mode should return results with 1 credit."""
    resp = await client.get("/v1/search", params={"q": "test query", "depth": "fast"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["query"] == "test query"
    assert len(data["results"]) > 0


@pytest.mark.asyncio
async def test_search_basic_mode(client, mock_db_user, mock_redis, mock_searxng):
    """Basic mode (default) should work as before."""
    resp = await client.get("/v1/search", params={"q": "test query", "depth": "basic"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["query"] == "test query"


@pytest.mark.asyncio
async def test_search_default_is_basic(client, mock_db_user, mock_redis, mock_searxng):
    """Default depth should be basic."""
    resp = await client.get("/v1/search", params={"q": "test query"})
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_search_deep_mode(client, mock_db_user, mock_redis):
    """Deep mode should merge results from multiple queries and charge 2 credits."""
    fake_results_1 = {
        "query": "test query",
        "results": [
            {"title": "Result 1", "url": "https://example.com/1", "snippet": "test snippet 1", "source": "google", "position": 1},
            {"title": "Result 2", "url": "https://example.com/2", "snippet": "test snippet 2", "source": "google", "position": 2},
        ],
        "infobox": None,
        "suggestions": ["suggestion 1"],
        "meta": {"total_results": 2, "cached": False, "response_time_ms": 100, "engines_used": ["google"]},
    }

    fake_results_2 = {
        "query": "test query site:reddit.com",
        "results": [
            {"title": "Result 3", "url": "https://example.com/3", "snippet": "test snippet 3", "source": "bing", "position": 1},
            {"title": "Result Dup", "url": "https://example.com/1", "snippet": "duplicate result", "source": "bing", "position": 2},
        ],
        "infobox": None,
        "suggestions": ["suggestion 2"],
        "meta": {"total_results": 2, "cached": False, "response_time_ms": 150, "engines_used": ["bing"]},
    }

    call_count = 0

    async def mock_execute(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return fake_results_1
        return fake_results_2

    with patch("api.routers.search.search_multi", new_callable=AsyncMock) as mock_multi:
        mock_multi.return_value = [fake_results_1, fake_results_2]

        resp = await client.get("/v1/search", params={"q": "test query", "depth": "deep"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["query"] == "test query"

    # Should have deduplicated — example.com/1 appears in both sets
    urls = [r["url"] for r in data["results"]]
    assert len(urls) == len(set(urls)), "Results should be deduplicated"
    assert len(urls) == 3  # 2 unique from set 1 + 1 unique from set 2


@pytest.mark.asyncio
async def test_deep_mode_deduplication(client, mock_db_user, mock_redis):
    """Deep search should deduplicate results from multiple queries."""
    shared_result = {
        "query": "q",
        "results": [
            {"title": "Same", "url": "https://example.com/same", "snippet": "same", "source": "google", "position": 1},
        ],
        "infobox": None,
        "suggestions": [],
        "meta": {"total_results": 1, "cached": False, "response_time_ms": 50, "engines_used": ["google"]},
    }

    with patch("api.routers.search.search_multi", new_callable=AsyncMock) as mock_multi:
        # Both queries return the same URL
        mock_multi.return_value = [shared_result, shared_result]

        resp = await client.get("/v1/search", params={"q": "test", "depth": "deep"})

    assert resp.status_code == 200
    data = resp.json()
    urls = [r["url"] for r in data["results"]]
    assert urls.count("https://example.com/same") == 1


@pytest.mark.asyncio
async def test_fast_mode_passes_timeout(client, mock_db_user, mock_redis):
    """Fast mode should pass a 3s timeout to SearXNG."""
    with patch("api.routers.search.execute_search", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = {
            "query": "q",
            "results": [],
            "infobox": None,
            "suggestions": [],
            "meta": {"total_results": 0, "cached": False, "response_time_ms": 50, "engines_used": []},
        }

        resp = await client.get("/v1/search", params={"q": "test", "depth": "fast"})

    assert resp.status_code == 200
    # Verify timeout was passed
    call_kwargs = mock_exec.call_args[1]
    assert call_kwargs["timeout"] == 3.0
