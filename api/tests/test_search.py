"""Tests for search endpoints — /v1/search, /v1/news, /v1/images, /v1/suggest, /v1/search/ai."""

import pytest


@pytest.mark.asyncio
async def test_web_search(client, mock_db_user, mock_redis, mock_searxng):
    resp = await client.get("/v1/search", params={"q": "test query"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["query"] == "test query"
    assert len(data["results"]) == 2
    assert data["results"][0]["title"] == "Test Result 1"
    assert data["meta"]["cached"] is False
    assert "X-RateLimit-Limit" in resp.headers
    assert "X-Credits-Used" in resp.headers


@pytest.mark.asyncio
async def test_web_search_cache_hit(client, mock_db_user, mock_redis, mock_searxng):
    # First request — cache miss
    resp1 = await client.get("/v1/search", params={"q": "cached query"})
    assert resp1.status_code == 200
    assert resp1.json()["meta"]["cached"] is False

    # Second request — should hit cache
    resp2 = await client.get("/v1/search", params={"q": "cached query"})
    assert resp2.status_code == 200
    assert resp2.json()["meta"]["cached"] is True

    # SearXNG should only have been called once
    assert mock_searxng.call_count == 1


@pytest.mark.asyncio
async def test_news_search(client, mock_db_user, mock_redis, mock_searxng):
    resp = await client.get("/v1/news", params={"q": "breaking news"})
    assert resp.status_code == 200
    # Verify it called SearXNG with news category
    call_kwargs = mock_searxng.call_args[1]
    assert "news" in call_kwargs["categories"]


@pytest.mark.asyncio
async def test_image_search(client, mock_db_user, mock_redis, mock_searxng):
    resp = await client.get("/v1/images", params={"q": "cute cats"})
    assert resp.status_code == 200
    call_kwargs = mock_searxng.call_args[1]
    assert "images" in call_kwargs["categories"]


@pytest.mark.asyncio
async def test_ai_search(client, mock_db_user, mock_redis, mock_searxng):
    resp = await client.get("/v1/search/ai", params={"q": "what is kubernetes"})
    assert resp.status_code == 200
    data = resp.json()
    assert "context" in data
    assert "sources" in data
    assert len(data["sources"]) <= 5


@pytest.mark.asyncio
async def test_ai_search_costs_two_credits(client, mock_db_user, mock_redis, mock_searxng):
    resp = await client.get("/v1/search/ai", params={"q": "expensive query"})
    assert resp.status_code == 200
    # Check credits used is 2
    assert resp.headers["X-Credits-Used"] == "2"


@pytest.mark.asyncio
async def test_suggest(client, mock_db_user, mock_redis, mock_searxng):
    resp = await client.get("/v1/suggest", params={"q": "kube"})
    assert resp.status_code == 200
    data = resp.json()
    assert "suggestions" in data
    assert data["query"] == "kube"


@pytest.mark.asyncio
async def test_usage_endpoint(client, mock_db_user, mock_redis):
    resp = await client.get("/v1/usage")
    assert resp.status_code == 200
    data = resp.json()
    assert data["plan"] == "pro"
    assert data["credits_limit"] == 100000
    assert "credits_used" in data
    assert "credits_remaining" in data


@pytest.mark.asyncio
async def test_search_missing_query(client, mock_db_user, mock_redis):
    resp = await client.get("/v1/search")
    assert resp.status_code == 422  # Validation error


@pytest.mark.asyncio
async def test_search_query_too_long(client, mock_db_user, mock_redis):
    resp = await client.get("/v1/search", params={"q": "x" * 501})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_search_invalid_count(client, mock_db_user, mock_redis):
    resp = await client.get("/v1/search", params={"q": "test", "count": 100})
    assert resp.status_code == 422
