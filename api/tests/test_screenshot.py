"""Tests for screenshot endpoint — POST /v1/screenshot."""

import base64

import pytest
from unittest.mock import AsyncMock, patch, MagicMock


@pytest.fixture
def mock_browser_pool():
    """Mock browser pool for screenshot tests."""
    fake_image = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100  # Fake PNG header
    mock_page = MagicMock()
    mock_page.set_viewport_size = AsyncMock()
    mock_page.goto = AsyncMock()
    mock_page.screenshot = AsyncMock(return_value=fake_image)
    mock_page.context = MagicMock()
    mock_page.close = AsyncMock()

    pool = MagicMock()
    pool.get_page = AsyncMock(return_value=mock_page)
    pool.release_page = AsyncMock()

    with patch("api.routers.screenshot.get_browser_pool", return_value=pool):
        yield pool, mock_page, fake_image


@pytest.mark.asyncio
async def test_screenshot_json_response(client, mock_db_user, mock_redis, mock_browser_pool):
    """Test screenshot returns base64 JSON response."""
    pool, mock_page, fake_image = mock_browser_pool
    resp = await client.post("/v1/screenshot", json={
        "url": "https://example.com",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["url"] == "https://example.com/"
    assert data["format"] == "png"
    assert data["image_base64"] == base64.b64encode(fake_image).decode()
    assert data["meta"]["credits_used"] == 1


@pytest.mark.asyncio
async def test_screenshot_image_response(client, mock_db_user, mock_redis, mock_browser_pool):
    """Test screenshot returns raw image when Accept: image/* header is set."""
    pool, mock_page, fake_image = mock_browser_pool
    resp = await client.post(
        "/v1/screenshot",
        json={"url": "https://example.com"},
        headers={"accept": "image/png"},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert resp.content == fake_image


@pytest.mark.asyncio
async def test_screenshot_custom_viewport(client, mock_db_user, mock_redis, mock_browser_pool):
    """Test screenshot with custom viewport dimensions."""
    pool, mock_page, _ = mock_browser_pool
    resp = await client.post("/v1/screenshot", json={
        "url": "https://example.com",
        "width": 1920,
        "height": 1080,
    })
    assert resp.status_code == 200
    mock_page.set_viewport_size.assert_called_with({"width": 1920, "height": 1080})


@pytest.mark.asyncio
async def test_screenshot_jpeg_format(client, mock_db_user, mock_redis, mock_browser_pool):
    """Test JPEG screenshot format."""
    pool, mock_page, _ = mock_browser_pool
    resp = await client.post("/v1/screenshot", json={
        "url": "https://example.com",
        "format": "jpeg",
        "quality": 90,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["format"] == "jpeg"


@pytest.mark.asyncio
async def test_screenshot_no_auth(client, mock_redis):
    """Test that screenshot requires authentication."""
    resp = await client.post("/v1/screenshot", json={
        "url": "https://example.com",
    })
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_screenshot_browser_pool_unavailable(client, mock_db_user, mock_redis):
    """Test 503 when browser pool is not initialized."""
    with patch("api.routers.screenshot.get_browser_pool", return_value=None):
        resp = await client.post("/v1/screenshot", json={
            "url": "https://example.com",
        })
    assert resp.status_code == 503
