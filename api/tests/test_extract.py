"""Tests for extraction endpoint — POST /v1/extract."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from api.services.extractor import ExtractionResult


@pytest.fixture
def mock_browser_pool():
    """Mock browser pool for extraction tests."""
    pool = MagicMock()
    pool.render_url = AsyncMock(return_value=(
        '<html><head><script type="application/ld+json">{"name":"Test","price":"9.99"}</script></head><body><h1>Test</h1></body></html>',
        "Test Page",
    ))
    pool.status = {"pool_size": 3, "available": 3, "active": 0, "ready": True}

    with patch("api.routers.extract.get_browser_pool", return_value=pool):
        yield pool


@pytest.mark.asyncio
async def test_extract_with_schema(client, mock_db_user, mock_redis, mock_browser_pool):
    """Test extraction with a JSON schema — rule-based should match JSON-LD."""
    resp = await client.post("/v1/extract", json={
        "url": "https://example.com/product",
        "schema": {"name": "string", "price": "string"},
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["url"] == "https://example.com/product"
    assert data["meta"]["extraction_method"] == "rule"
    assert data["meta"]["cached"] is False
    assert data["meta"]["credits_used"] == 1
    assert "name" in data["data"]


@pytest.mark.asyncio
async def test_extract_with_prompt(client, mock_db_user, mock_redis, mock_browser_pool):
    """Test extraction with a natural language prompt — falls back to LLM."""
    mock_llm_result = ExtractionResult(
        data={"summary": "A test page"},
        extraction_method="llm",
        model_used="gpt-4o-mini",
        tokens_used=150,
    )
    with patch("api.routers.extract.extract", new_callable=AsyncMock, return_value=mock_llm_result):
        resp = await client.post("/v1/extract", json={
            "url": "https://example.com",
            "prompt": "Extract a summary of this page",
        })
    assert resp.status_code == 200
    data = resp.json()
    assert data["meta"]["extraction_method"] == "llm"
    assert data["meta"]["model_used"] == "gpt-4o-mini"
    assert data["meta"]["credits_used"] == 2  # LLM surcharge


@pytest.mark.asyncio
async def test_extract_cache_hit(client, mock_db_user, mock_redis, mock_browser_pool):
    """Test that cached extraction results are returned."""
    # First request — cache miss
    resp1 = await client.post("/v1/extract", json={
        "url": "https://example.com/cache-test",
        "schema": {"name": "string"},
    })
    assert resp1.status_code == 200
    assert resp1.json()["meta"]["cached"] is False

    # Second request — cache hit
    resp2 = await client.post("/v1/extract", json={
        "url": "https://example.com/cache-test",
        "schema": {"name": "string"},
    })
    assert resp2.status_code == 200
    assert resp2.json()["meta"]["cached"] is True

    # Browser pool should only have been called once
    assert mock_browser_pool.render_url.call_count == 1


@pytest.mark.asyncio
async def test_extract_requires_schema_or_prompt(client, mock_db_user, mock_redis, mock_browser_pool):
    """Test that extract requires either schema or prompt."""
    resp = await client.post("/v1/extract", json={
        "url": "https://example.com",
    })
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_extract_no_auth(client, mock_redis):
    """Test that extract requires authentication."""
    resp = await client.post("/v1/extract", json={
        "url": "https://example.com",
        "prompt": "test",
    })
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_extract_browser_pool_unavailable(client, mock_db_user, mock_redis):
    """Test 503 when browser pool is not initialized."""
    with patch("api.routers.extract.get_browser_pool", return_value=None):
        resp = await client.post("/v1/extract", json={
            "url": "https://example.com",
            "prompt": "test",
        })
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_extract_render_failure(client, mock_db_user, mock_redis, mock_browser_pool):
    """Test 502 when page rendering fails."""
    mock_browser_pool.render_url = AsyncMock(side_effect=Exception("Timeout"))
    resp = await client.post("/v1/extract", json={
        "url": "https://example.com/timeout",
        "schema": {"title": "string"},
    })
    assert resp.status_code == 502


@pytest.mark.asyncio
async def test_extract_llm_fallback_on_failure(client, mock_db_user, mock_redis, mock_browser_pool):
    """Test that extraction falls back to raw text when LLM fails."""
    mock_browser_pool.render_url = AsyncMock(return_value=(
        "<html><body><p>Hello world</p></body></html>",
        "Simple Page",
    ))
    with patch("api.routers.extract.extract", new_callable=AsyncMock, side_effect=RuntimeError("LLM failed")):
        resp = await client.post("/v1/extract", json={
            "url": "https://example.com/fallback",
            "prompt": "extract something",
        })
    assert resp.status_code == 200
    data = resp.json()
    assert data["meta"]["extraction_method"] == "raw"
