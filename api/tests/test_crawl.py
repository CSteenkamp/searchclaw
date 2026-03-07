"""Tests for crawl endpoint — POST /v1/crawl."""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock


@pytest.fixture
def mock_celery_task():
    """Mock the Celery crawl task."""
    mock_task = MagicMock()
    mock_task.delay = MagicMock()

    with patch("api.workers.crawl_worker.crawl_and_extract", mock_task):
        yield mock_task


@pytest.fixture
def mock_redis_for_jobs(mock_redis):
    """Extend mock_redis with raw Redis ops for job tracking."""
    job_store = {}

    async def fake_set(key, value, ex=None):
        job_store[key] = value

    async def fake_get(key):
        return job_store.get(key)

    async def fake_lrange(key, start, end):
        return job_store.get(key, [])

    mock_client = MagicMock()
    mock_client.set = AsyncMock(side_effect=fake_set)
    mock_client.get = AsyncMock(side_effect=fake_get)
    mock_client.lrange = AsyncMock(side_effect=fake_lrange)

    with patch("api.routers.crawl.get_redis_client", return_value=mock_client), \
         patch("api.routers.jobs.get_redis_client", return_value=mock_client):
        yield mock_client, job_store


@pytest.mark.asyncio
async def test_crawl_creates_job(client, mock_db_user, mock_redis, mock_redis_for_jobs, mock_celery_task):
    """Test that crawl endpoint creates a job and returns job_id."""
    resp = await client.post("/v1/crawl", json={
        "url": "https://example.com/products",
        "schema": {"name": "string", "price": "number"},
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "processing"
    assert data["job_id"].startswith("job_")
    assert "/v1/jobs/" in data["poll_url"]
    mock_celery_task.delay.assert_called_once()


@pytest.mark.asyncio
async def test_crawl_with_pagination(client, mock_db_user, mock_redis, mock_redis_for_jobs, mock_celery_task):
    """Test crawl with pagination config."""
    resp = await client.post("/v1/crawl", json={
        "url": "https://example.com/list",
        "schema": {"title": "string"},
        "pagination": {"type": "next_button", "selector": ".next", "max_pages": 5},
        "max_items": 50,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["job_id"].startswith("job_")


@pytest.mark.asyncio
async def test_crawl_no_auth(client, mock_redis):
    """Test that crawl requires authentication."""
    resp = await client.post("/v1/crawl", json={
        "url": "https://example.com",
    })
    assert resp.status_code == 401
