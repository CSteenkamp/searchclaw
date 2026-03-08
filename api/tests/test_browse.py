"""Tests for browse endpoint — POST /v1/browse."""

import base64

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def mock_browser_pool():
    """Mock browser pool for browse tests."""
    page = AsyncMock()
    page.url = "https://example.com/after"
    page.content = AsyncMock(return_value="<html><body><h1>Hello</h1></body></html>")
    page.title = AsyncMock(return_value="Test Page")
    page.screenshot = AsyncMock(return_value=b"\x89PNG fake image data")
    page.evaluate = AsyncMock(return_value=42)
    page.keyboard = AsyncMock()
    page.context = MagicMock()

    # Element mock for selector-based operations
    element = AsyncMock()
    element.screenshot = AsyncMock(return_value=b"\x89PNG element data")
    element.inner_html = AsyncMock(return_value="<div>User data</div>")
    page.query_selector = AsyncMock(return_value=element)

    pool = MagicMock()
    pool.get_page = AsyncMock(return_value=page)
    pool.release_page = AsyncMock()
    pool.status = {"pool_size": 3, "available": 3, "active": 0, "ready": True}

    with patch("api.routers.browse.get_browser_pool", return_value=pool), \
         patch("api.routers.browse.get_proxy_manager", return_value=None), \
         patch("api.routers.browse.resolve_proxy_tier", return_value="none"):
        yield pool, page


@pytest.mark.asyncio
async def test_browse_basic_actions(client, mock_db_user, mock_redis, mock_browser_pool):
    """Test basic browse with wait + click actions."""
    pool, page = mock_browser_pool
    resp = await client.post("/v1/browse", json={
        "url": "https://example.com",
        "actions": [
            {"type": "wait", "selector": "#content"},
            {"type": "click", "selector": "#btn"},
        ],
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["url"] == "https://example.com/"
    assert len(data["results"]) == 2
    assert data["results"][0]["action"] == "wait"
    assert data["results"][0]["success"] is True
    assert data["results"][1]["action"] == "click"
    assert data["credits_used"] == 1


@pytest.mark.asyncio
async def test_browse_max_actions_exceeded(client, mock_db_user, mock_redis, mock_browser_pool):
    """Test that >20 actions returns 422."""
    actions = [{"type": "click", "selector": f"#btn{i}"} for i in range(21)]
    resp = await client.post("/v1/browse", json={
        "url": "https://example.com",
        "actions": actions,
    })
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_browse_empty_actions(client, mock_db_user, mock_redis, mock_browser_pool):
    """Test that empty actions list returns 422."""
    resp = await client.post("/v1/browse", json={
        "url": "https://example.com",
        "actions": [],
    })
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_browse_screenshot_returns_base64(client, mock_db_user, mock_redis, mock_browser_pool):
    """Test screenshot action returns base64 data."""
    pool, page = mock_browser_pool
    resp = await client.post("/v1/browse", json={
        "url": "https://example.com",
        "actions": [
            {"type": "screenshot", "full_page": True},
        ],
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["results"][0]["action"] == "screenshot"
    assert data["results"][0]["success"] is True
    assert data["results"][0]["data"] is not None
    # Verify it's valid base64
    base64.b64decode(data["results"][0]["data"])


@pytest.mark.asyncio
async def test_browse_extract_action(client, mock_db_user, mock_redis, mock_browser_pool):
    """Test extract action returns content."""
    pool, page = mock_browser_pool
    resp = await client.post("/v1/browse", json={
        "url": "https://example.com",
        "actions": [
            {"type": "extract", "selector": ".user-data", "format": "text"},
        ],
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["results"][0]["action"] == "extract"
    assert data["results"][0]["success"] is True
    assert data["results"][0]["content"] is not None


@pytest.mark.asyncio
async def test_browse_evaluate_action(client, mock_db_user, mock_redis, mock_browser_pool):
    """Test evaluate action returns JS result."""
    pool, page = mock_browser_pool
    resp = await client.post("/v1/browse", json={
        "url": "https://example.com",
        "actions": [
            {"type": "evaluate", "expression": "document.title"},
        ],
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["results"][0]["action"] == "evaluate"
    assert data["results"][0]["success"] is True
    assert data["results"][0]["data"] == "42"


@pytest.mark.asyncio
async def test_browse_fill_and_type_actions(client, mock_db_user, mock_redis, mock_browser_pool):
    """Test fill and type actions."""
    pool, page = mock_browser_pool
    resp = await client.post("/v1/browse", json={
        "url": "https://example.com",
        "actions": [
            {"type": "fill", "selector": "#email", "value": "user@test.com"},
            {"type": "type", "selector": "#password", "value": "secret", "delay": 50},
        ],
    })
    assert resp.status_code == 200
    data = resp.json()
    assert all(r["success"] for r in data["results"])
    page.fill.assert_called_once()
    page.type.assert_called_once()


@pytest.mark.asyncio
async def test_browse_scroll_action(client, mock_db_user, mock_redis, mock_browser_pool):
    """Test scroll action."""
    pool, page = mock_browser_pool
    resp = await client.post("/v1/browse", json={
        "url": "https://example.com",
        "actions": [
            {"type": "scroll", "direction": "down", "amount": 500},
        ],
    })
    assert resp.status_code == 200
    assert resp.json()["results"][0]["success"] is True
    page.evaluate.assert_called_with("window.scrollBy(0, 500)")


@pytest.mark.asyncio
async def test_browse_press_action(client, mock_db_user, mock_redis, mock_browser_pool):
    """Test press action."""
    pool, page = mock_browser_pool
    resp = await client.post("/v1/browse", json={
        "url": "https://example.com",
        "actions": [
            {"type": "press", "key": "Enter"},
        ],
    })
    assert resp.status_code == 200
    assert resp.json()["results"][0]["success"] is True
    page.keyboard.press.assert_called_with("Enter")


@pytest.mark.asyncio
async def test_browse_navigate_action(client, mock_db_user, mock_redis, mock_browser_pool):
    """Test navigate action."""
    pool, page = mock_browser_pool
    resp = await client.post("/v1/browse", json={
        "url": "https://example.com",
        "actions": [
            {"type": "navigate", "url": "https://other.com"},
        ],
    })
    assert resp.status_code == 200
    assert resp.json()["results"][0]["success"] is True
    page.goto.assert_called()


@pytest.mark.asyncio
async def test_browse_select_action(client, mock_db_user, mock_redis, mock_browser_pool):
    """Test select action."""
    pool, page = mock_browser_pool
    resp = await client.post("/v1/browse", json={
        "url": "https://example.com",
        "actions": [
            {"type": "select", "selector": "#country", "value": "US"},
        ],
    })
    assert resp.status_code == 200
    assert resp.json()["results"][0]["success"] is True
    page.select_option.assert_called_once()


@pytest.mark.asyncio
async def test_browse_error_handling(client, mock_db_user, mock_redis, mock_browser_pool):
    """Test that action errors are captured but execution continues."""
    pool, page = mock_browser_pool
    page.click = AsyncMock(side_effect=Exception("Element not found"))
    resp = await client.post("/v1/browse", json={
        "url": "https://example.com",
        "actions": [
            {"type": "click", "selector": "#missing"},
            {"type": "screenshot"},
        ],
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is False  # Overall failure
    assert data["results"][0]["success"] is False
    assert "Element not found" in data["results"][0]["error"]
    assert data["results"][1]["success"] is True  # Screenshot still runs


@pytest.mark.asyncio
async def test_browse_wait_failure_blocks(client, mock_db_user, mock_redis, mock_browser_pool):
    """Test that wait failure blocks subsequent actions."""
    pool, page = mock_browser_pool
    page.wait_for_selector = AsyncMock(side_effect=Exception("Timeout"))
    resp = await client.post("/v1/browse", json={
        "url": "https://example.com",
        "actions": [
            {"type": "wait", "selector": "#missing", "timeout": 1000},
            {"type": "click", "selector": "#btn"},
        ],
    })
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["results"]) == 1  # Click was skipped
    assert data["results"][0]["success"] is False


@pytest.mark.asyncio
async def test_browse_proxy_credits(client, mock_db_user, mock_redis):
    """Test that residential proxy costs 2 credits."""
    page = AsyncMock()
    page.url = "https://example.com/"
    page.context = MagicMock()

    pool = MagicMock()
    pool.get_page = AsyncMock(return_value=page)
    pool.release_page = AsyncMock()

    with patch("api.routers.browse.get_browser_pool", return_value=pool), \
         patch("api.routers.browse.get_proxy_manager", return_value=None), \
         patch("api.routers.browse.resolve_proxy_tier", return_value="residential"):
        resp = await client.post("/v1/browse", json={
            "url": "https://example.com",
            "actions": [{"type": "click", "selector": "#btn"}],
            "proxy": "residential",
        })
    assert resp.status_code == 200
    assert resp.json()["credits_used"] == 2


@pytest.mark.asyncio
async def test_browse_pool_unavailable(client, mock_db_user, mock_redis):
    """Test 503 when browser pool is not initialized."""
    with patch("api.routers.browse.get_browser_pool", return_value=None):
        resp = await client.post("/v1/browse", json={
            "url": "https://example.com",
            "actions": [{"type": "click", "selector": "#btn"}],
        })
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_browse_no_auth(client, mock_redis):
    """Test that browse requires authentication."""
    resp = await client.post("/v1/browse", json={
        "url": "https://example.com",
        "actions": [{"type": "click", "selector": "#btn"}],
    })
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_browse_action_validation(client, mock_db_user, mock_redis, mock_browser_pool):
    """Test action field validation — missing required fields."""
    # navigate without url
    resp = await client.post("/v1/browse", json={
        "url": "https://example.com",
        "actions": [{"type": "navigate"}],
    })
    assert resp.status_code == 422

    # fill without value
    resp = await client.post("/v1/browse", json={
        "url": "https://example.com",
        "actions": [{"type": "fill", "selector": "#field"}],
    })
    assert resp.status_code == 422

    # scroll without direction
    resp = await client.post("/v1/browse", json={
        "url": "https://example.com",
        "actions": [{"type": "scroll"}],
    })
    assert resp.status_code == 422
