"""Tests for enhanced usage history endpoint — /v1/usage/history."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone


# ── Auth required ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_usage_history_requires_auth(client):
    """GET /v1/usage/history without auth returns 401."""
    resp = await client.get("/v1/usage/history")
    assert resp.status_code == 401


# ── JSON response ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_usage_history_json_empty(client, mock_db_user, mock_redis):
    """Empty usage returns valid JSON structure."""
    with patch("api.routers.usage.get_session") as mock_session:
        session = AsyncMock()
        result = MagicMock()
        result.all.return_value = []
        session.execute = AsyncMock(return_value=result)

        async def gen():
            yield session

        mock_session.return_value = gen()

        resp = await client.get("/v1/usage/history")
        assert resp.status_code == 200
        data = resp.json()
        assert data["usage"] == []
        assert data["total_credits"] == 0
        assert data["total_requests"] == 0
        assert "period" in data


@pytest.mark.asyncio
async def test_usage_history_json_with_data(client, mock_db_user, mock_redis):
    """Usage history returns grouped data by period and endpoint."""
    with patch("api.routers.usage.get_session") as mock_session:
        session = AsyncMock()

        # Simulate two rows: search and extract on same day
        row1 = MagicMock()
        row1.period = "2026-03-07"
        row1.endpoint = "search"
        row1.credits = 800
        row1.requests = 800
        row1.cached_count = 188
        row1.avg_ms = 210.0

        row2 = MagicMock()
        row2.period = "2026-03-07"
        row2.endpoint = "extract"
        row2.credits = 500
        row2.requests = 500
        row2.cached_count = 60
        row2.avg_ms = 580.0

        result = MagicMock()
        result.all.return_value = [row1, row2]
        session.execute = AsyncMock(return_value=result)

        async def gen():
            yield session

        mock_session.return_value = gen()

        resp = await client.get("/v1/usage/history?group_by=day")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["usage"]) == 1
        period = data["usage"][0]
        assert period["total_credits"] == 1300
        assert period["requests"] == 1300
        assert "search" in period["by_endpoint"]
        assert "extract" in period["by_endpoint"]
        assert period["by_endpoint"]["search"]["credits"] == 800
        assert period["by_endpoint"]["search"]["cached_pct"] == 23.5
        assert data["total_credits"] == 1300


# ── Date range filtering ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_usage_history_date_range(client, mock_db_user, mock_redis):
    """Date range params are accepted without error."""
    with patch("api.routers.usage.get_session") as mock_session:
        session = AsyncMock()
        result = MagicMock()
        result.all.return_value = []
        session.execute = AsyncMock(return_value=result)

        async def gen():
            yield session

        mock_session.return_value = gen()

        resp = await client.get("/v1/usage/history?from=2026-03-01&to=2026-03-08")
        assert resp.status_code == 200
        data = resp.json()
        assert data["period"]["from"] == "2026-03-01"
        assert data["period"]["to"] == "2026-03-08"


# ── Endpoint filtering ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_usage_history_endpoint_filter(client, mock_db_user, mock_redis):
    """Endpoint filter param is accepted."""
    with patch("api.routers.usage.get_session") as mock_session:
        session = AsyncMock()
        result = MagicMock()
        result.all.return_value = []
        session.execute = AsyncMock(return_value=result)

        async def gen():
            yield session

        mock_session.return_value = gen()

        resp = await client.get("/v1/usage/history?endpoint=search")
        assert resp.status_code == 200


# ── Group by validation ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_usage_history_group_by_hour(client, mock_db_user, mock_redis):
    """group_by=hour is accepted."""
    with patch("api.routers.usage.get_session") as mock_session:
        session = AsyncMock()
        result = MagicMock()
        result.all.return_value = []
        session.execute = AsyncMock(return_value=result)

        async def gen():
            yield session

        mock_session.return_value = gen()

        resp = await client.get("/v1/usage/history?group_by=hour")
        assert resp.status_code == 200


@pytest.mark.asyncio
async def test_usage_history_invalid_group_by(client, mock_db_user, mock_redis):
    """Invalid group_by value returns 422."""
    resp = await client.get("/v1/usage/history?group_by=century")
    assert resp.status_code == 422


# ── CSV export ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_usage_history_csv_empty(client, mock_db_user, mock_redis):
    """CSV export with no data returns header-only CSV."""
    with patch("api.routers.usage.get_session") as mock_session:
        session = AsyncMock()
        result = MagicMock()
        result.all.return_value = []
        session.execute = AsyncMock(return_value=result)

        async def gen():
            yield session

        mock_session.return_value = gen()

        resp = await client.get("/v1/usage/history?format=csv")
        assert resp.status_code == 200
        assert "text/csv" in resp.headers.get("content-type", "")
        body = resp.text
        assert "date,endpoint,credits,requests,cached_pct,avg_response_ms" in body


@pytest.mark.asyncio
async def test_usage_history_csv_with_data(client, mock_db_user, mock_redis):
    """CSV export includes data rows."""
    with patch("api.routers.usage.get_session") as mock_session:
        session = AsyncMock()

        row = MagicMock()
        row.period = "2026-03-07"
        row.endpoint = "search"
        row.credits = 100
        row.requests = 100
        row.cached_count = 25
        row.avg_ms = 200.0

        result = MagicMock()
        result.all.return_value = [row]
        session.execute = AsyncMock(return_value=result)

        async def gen():
            yield session

        mock_session.return_value = gen()

        resp = await client.get("/v1/usage/history?format=csv")
        assert resp.status_code == 200
        lines = resp.text.strip().split("\n")
        assert len(lines) == 2  # header + 1 data row
        assert "search" in lines[1]


@pytest.mark.asyncio
async def test_usage_history_csv_content_disposition(client, mock_db_user, mock_redis):
    """CSV export sets Content-Disposition header."""
    with patch("api.routers.usage.get_session") as mock_session:
        session = AsyncMock()
        result = MagicMock()
        result.all.return_value = []
        session.execute = AsyncMock(return_value=result)

        async def gen():
            yield session

        mock_session.return_value = gen()

        resp = await client.get("/v1/usage/history?format=csv")
        assert "usage_export.csv" in resp.headers.get("content-disposition", "")


@pytest.mark.asyncio
async def test_usage_history_invalid_format(client, mock_db_user, mock_redis):
    """Invalid format value returns 422."""
    resp = await client.get("/v1/usage/history?format=xml")
    assert resp.status_code == 422
