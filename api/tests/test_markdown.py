"""Tests for markdown endpoint — POST /v1/markdown."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock


@pytest.fixture
def mock_browser_pool():
    """Mock browser pool for markdown tests."""
    pool = MagicMock()
    pool.render_url = AsyncMock(return_value=(
        "<html><body><h1>Hello World</h1><p>This is a test paragraph.</p></body></html>",
        "Hello World",
    ))

    with patch("api.routers.markdown.get_browser_pool", return_value=pool):
        yield pool


@pytest.mark.asyncio
async def test_markdown_conversion(client, mock_db_user, mock_redis, mock_browser_pool):
    """Test basic URL to markdown conversion."""
    resp = await client.post("/v1/markdown", json={
        "url": "https://example.com",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["url"] == "https://example.com/"
    assert data["title"] == "Hello World"
    assert "Hello World" in data["markdown"]
    assert data["meta"]["cached"] is False
    assert data["meta"]["credits_used"] == 1


@pytest.mark.asyncio
async def test_markdown_cache_hit(client, mock_db_user, mock_redis, mock_browser_pool):
    """Test cached markdown results."""
    resp1 = await client.post("/v1/markdown", json={
        "url": "https://example.com/cached",
    })
    assert resp1.status_code == 200
    assert resp1.json()["meta"]["cached"] is False

    resp2 = await client.post("/v1/markdown", json={
        "url": "https://example.com/cached",
    })
    assert resp2.status_code == 200
    assert resp2.json()["meta"]["cached"] is True
    assert mock_browser_pool.render_url.call_count == 1


@pytest.mark.asyncio
async def test_markdown_no_auth(client, mock_redis):
    """Test that markdown requires authentication."""
    resp = await client.post("/v1/markdown", json={
        "url": "https://example.com",
    })
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_markdown_browser_pool_unavailable(client, mock_db_user, mock_redis):
    """Test 503 when browser pool is not initialized."""
    with patch("api.routers.markdown.get_browser_pool", return_value=None):
        resp = await client.post("/v1/markdown", json={
            "url": "https://example.com",
        })
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_markdown_render_failure(client, mock_db_user, mock_redis, mock_browser_pool):
    """Test 502 when page rendering fails."""
    mock_browser_pool.render_url = AsyncMock(side_effect=Exception("Timeout"))
    resp = await client.post("/v1/markdown", json={
        "url": "https://example.com/timeout",
    })
    assert resp.status_code == 502


@pytest.mark.asyncio
async def test_markdown_word_count(client, mock_db_user, mock_redis, mock_browser_pool):
    """Test that word count is included in meta."""
    resp = await client.post("/v1/markdown", json={
        "url": "https://example.com/words",
    })
    assert resp.status_code == 200
    assert "word_count" in resp.json()["meta"]
    assert resp.json()["meta"]["word_count"] > 0
