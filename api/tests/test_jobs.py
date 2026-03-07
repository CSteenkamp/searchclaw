"""Tests for jobs endpoint — GET /v1/jobs/{job_id}."""

import json

import pytest
from unittest.mock import patch, MagicMock, AsyncMock


@pytest.fixture
def mock_redis_jobs(mock_redis):
    """Mock Redis with job status data."""
    job_store = {}

    async def fake_get(key):
        return job_store.get(key)

    async def fake_lrange(key, start, end):
        return job_store.get(key, [])

    mock_client = MagicMock()
    mock_client.get = AsyncMock(side_effect=fake_get)
    mock_client.lrange = AsyncMock(side_effect=fake_lrange)

    with patch("api.routers.jobs.get_redis_client", return_value=mock_client):
        yield mock_client, job_store


@pytest.mark.asyncio
async def test_job_status_queued(client, mock_db_user, mock_redis, mock_redis_jobs):
    """Test getting status of a queued job."""
    mock_client, job_store = mock_redis_jobs
    job_store["job:job_abc123:status"] = json.dumps({
        "status": "queued", "pages_crawled": 0, "items_extracted": 0,
    })

    resp = await client.get("/v1/jobs/job_abc123")
    assert resp.status_code == 200
    data = resp.json()
    assert data["job_id"] == "job_abc123"
    assert data["status"] == "queued"
    assert data["data"] is None


@pytest.mark.asyncio
async def test_job_status_processing(client, mock_db_user, mock_redis, mock_redis_jobs):
    """Test getting status of a processing job."""
    mock_client, job_store = mock_redis_jobs
    job_store["job:job_proc123:status"] = json.dumps({
        "status": "processing", "pages_crawled": 3, "total_pages": 10, "items_extracted": 15,
    })

    resp = await client.get("/v1/jobs/job_proc123")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "processing"
    assert data["progress"]["pages_crawled"] == 3
    assert data["progress"]["items_extracted"] == 15


@pytest.mark.asyncio
async def test_job_status_completed(client, mock_db_user, mock_redis, mock_redis_jobs):
    """Test getting status and results of a completed job."""
    mock_client, job_store = mock_redis_jobs
    job_store["job:job_done123:status"] = json.dumps({
        "status": "completed", "pages_crawled": 5, "total_pages": 5,
        "items_extracted": 25, "duration_ms": 5000, "credits_used": 5,
    })
    job_store["job:job_done123:results"] = [
        json.dumps({"name": "Item 1", "price": 10}),
        json.dumps({"name": "Item 2", "price": 20}),
    ]

    resp = await client.get("/v1/jobs/job_done123")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "completed"
    assert len(data["data"]) == 2
    assert data["meta"]["total_items"] == 25
    assert data["meta"]["credits_used"] == 5


@pytest.mark.asyncio
async def test_job_status_failed(client, mock_db_user, mock_redis, mock_redis_jobs):
    """Test getting status of a failed job."""
    mock_client, job_store = mock_redis_jobs
    job_store["job:job_fail123:status"] = json.dumps({
        "status": "failed", "error": "Connection timeout",
    })

    resp = await client.get("/v1/jobs/job_fail123")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "failed"
    assert data["error"] == "Connection timeout"


@pytest.mark.asyncio
async def test_job_not_found(client, mock_db_user, mock_redis, mock_redis_jobs):
    """Test 404 for non-existent job."""
    resp = await client.get("/v1/jobs/job_nonexistent")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_job_no_auth(client, mock_redis):
    """Test that jobs endpoint requires authentication."""
    resp = await client.get("/v1/jobs/job_abc123")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_job_redis_unavailable(client, mock_db_user, mock_redis):
    """Test 503 when Redis is not available."""
    with patch("api.routers.jobs.get_redis_client", return_value=None):
        resp = await client.get("/v1/jobs/job_abc123")
    assert resp.status_code == 503
