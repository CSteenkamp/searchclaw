"""Tests for webhook delivery system — HMAC signing, retries, crawl/pipeline integration."""

import hashlib
import hmac
import json

import pytest
import httpx
from unittest.mock import AsyncMock, MagicMock, patch

from api.services.webhook import deliver_webhook


# ---------------------------------------------------------------------------
# Unit tests for deliver_webhook
# ---------------------------------------------------------------------------

class TestWebhookDelivery:
    """Unit tests for the webhook delivery service."""

    @pytest.mark.asyncio
    async def test_successful_delivery(self):
        """Webhook is delivered on first attempt."""
        mock_response = httpx.Response(200)

        with patch("api.services.webhook.httpx.AsyncClient") as MockClient:
            instance = AsyncMock()
            instance.post = AsyncMock(return_value=mock_response)
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = instance

            result = await deliver_webhook(
                job_id="job_abc123",
                payload={"status": "completed", "data": [{"name": "test"}]},
                webhook_url="https://example.com/webhook",
            )

        assert result["webhook_delivered"] is True
        assert result["webhook_attempts"] == 1
        assert result["webhook_last_error"] is None
        instance.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_hmac_signature(self):
        """Webhook includes correct HMAC-SHA256 signature when secret provided."""
        mock_response = httpx.Response(200)
        captured_headers = {}

        async def capture_post(url, content, headers):
            captured_headers.update(headers)
            return mock_response

        with patch("api.services.webhook.httpx.AsyncClient") as MockClient:
            instance = AsyncMock()
            instance.post = AsyncMock(side_effect=capture_post)
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = instance

            payload = {"status": "completed", "job_id": "job_abc123"}
            secret = "my_webhook_secret"

            await deliver_webhook(
                job_id="job_abc123",
                payload=payload,
                webhook_url="https://example.com/webhook",
                webhook_secret=secret,
            )

        assert "X-SearchClaw-Signature" in captured_headers
        # Verify the signature is correct
        body = json.dumps(payload, separators=(",", ":"), default=str).encode()
        expected_sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        assert captured_headers["X-SearchClaw-Signature"] == f"sha256={expected_sig}"

    @pytest.mark.asyncio
    async def test_no_signature_without_secret(self):
        """No signature header when webhook_secret is not provided."""
        mock_response = httpx.Response(200)
        captured_headers = {}

        async def capture_post(url, content, headers):
            captured_headers.update(headers)
            return mock_response

        with patch("api.services.webhook.httpx.AsyncClient") as MockClient:
            instance = AsyncMock()
            instance.post = AsyncMock(side_effect=capture_post)
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = instance

            await deliver_webhook(
                job_id="job_abc123",
                payload={"status": "completed"},
                webhook_url="https://example.com/webhook",
            )

        assert "X-SearchClaw-Signature" not in captured_headers

    @pytest.mark.asyncio
    async def test_correct_headers(self):
        """Webhook includes all required headers."""
        mock_response = httpx.Response(200)
        captured_headers = {}

        async def capture_post(url, content, headers):
            captured_headers.update(headers)
            return mock_response

        with patch("api.services.webhook.httpx.AsyncClient") as MockClient:
            instance = AsyncMock()
            instance.post = AsyncMock(side_effect=capture_post)
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = instance

            await deliver_webhook(
                job_id="job_test123",
                payload={"status": "failed"},
                webhook_url="https://example.com/webhook",
                event="job.failed",
            )

        assert captured_headers["Content-Type"] == "application/json"
        assert captured_headers["X-SearchClaw-Event"] == "job.failed"
        assert captured_headers["X-SearchClaw-Job-Id"] == "job_test123"
        assert captured_headers["User-Agent"] == "SearchClaw-Webhook/1.0"

    @pytest.mark.asyncio
    async def test_retry_on_server_error(self):
        """Webhook retries on 5xx responses and eventually succeeds."""
        call_count = 0

        async def flaky_post(url, content, headers):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                return httpx.Response(500)
            return httpx.Response(200)

        with patch("api.services.webhook.httpx.AsyncClient") as MockClient, \
             patch("api.services.webhook.asyncio.sleep", new_callable=AsyncMock):
            instance = AsyncMock()
            instance.post = AsyncMock(side_effect=flaky_post)
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = instance

            result = await deliver_webhook(
                job_id="job_retry",
                payload={"status": "completed"},
                webhook_url="https://example.com/webhook",
            )

        assert result["webhook_delivered"] is True
        assert result["webhook_attempts"] == 3

    @pytest.mark.asyncio
    async def test_exhausted_retries(self):
        """Webhook returns failure after 3 failed attempts."""
        async def always_fail(url, content, headers):
            return httpx.Response(500)

        with patch("api.services.webhook.httpx.AsyncClient") as MockClient, \
             patch("api.services.webhook.asyncio.sleep", new_callable=AsyncMock):
            instance = AsyncMock()
            instance.post = AsyncMock(side_effect=always_fail)
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = instance

            result = await deliver_webhook(
                job_id="job_fail",
                payload={"status": "completed"},
                webhook_url="https://example.com/webhook",
            )

        assert result["webhook_delivered"] is False
        assert result["webhook_attempts"] == 3
        assert result["webhook_last_error"] == "HTTP 500"

    @pytest.mark.asyncio
    async def test_retry_on_connection_error(self):
        """Webhook retries on connection errors."""
        call_count = 0

        async def error_then_success(url, content, headers):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise httpx.ConnectError("Connection refused")
            return httpx.Response(200)

        with patch("api.services.webhook.httpx.AsyncClient") as MockClient, \
             patch("api.services.webhook.asyncio.sleep", new_callable=AsyncMock):
            instance = AsyncMock()
            instance.post = AsyncMock(side_effect=error_then_success)
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = instance

            result = await deliver_webhook(
                job_id="job_conn",
                payload={"status": "completed"},
                webhook_url="https://example.com/webhook",
            )

        assert result["webhook_delivered"] is True
        assert result["webhook_attempts"] == 2


# ---------------------------------------------------------------------------
# Integration tests: crawl endpoint with webhook params
# ---------------------------------------------------------------------------

class TestCrawlWebhookIntegration:
    """Test that the crawl endpoint accepts and stores webhook parameters."""

    @pytest.fixture
    def mock_celery_task(self):
        mock_task = MagicMock()
        mock_task.delay = MagicMock()
        with patch("api.workers.crawl_worker.crawl_and_extract", mock_task):
            yield mock_task

    @pytest.fixture
    def mock_redis_for_jobs(self, mock_redis):
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
    async def test_crawl_accepts_webhook_url(self, client, mock_db_user, mock_redis, mock_redis_for_jobs, mock_celery_task):
        """Crawl endpoint accepts webhook_url parameter."""
        resp = await client.post("/v1/crawl", json={
            "url": "https://example.com/products",
            "schema": {"name": "string"},
            "webhook_url": "https://myapp.com/webhook",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "processing"

        # Verify webhook_url was passed to Celery
        call_kwargs = mock_celery_task.delay.call_args
        assert call_kwargs.kwargs["webhook_url"] == "https://myapp.com/webhook"

    @pytest.mark.asyncio
    async def test_crawl_accepts_webhook_secret(self, client, mock_db_user, mock_redis, mock_redis_for_jobs, mock_celery_task):
        """Crawl endpoint accepts webhook_secret parameter."""
        resp = await client.post("/v1/crawl", json={
            "url": "https://example.com/products",
            "schema": {"name": "string"},
            "webhook_url": "https://myapp.com/webhook",
            "webhook_secret": "secret123",
        })
        assert resp.status_code == 200

        call_kwargs = mock_celery_task.delay.call_args
        assert call_kwargs.kwargs["webhook_secret"] == "secret123"

    @pytest.mark.asyncio
    async def test_crawl_stores_webhook_in_redis(self, client, mock_db_user, mock_redis, mock_redis_for_jobs, mock_celery_task):
        """Webhook config is stored in the Redis job record."""
        _, job_store = mock_redis_for_jobs

        resp = await client.post("/v1/crawl", json={
            "url": "https://example.com/products",
            "schema": {"name": "string"},
            "webhook_url": "https://myapp.com/webhook",
            "webhook_secret": "secret123",
        })
        assert resp.status_code == 200
        job_id = resp.json()["job_id"]

        stored = json.loads(job_store[f"job:{job_id}:status"])
        assert stored["webhook_url"] == "https://myapp.com/webhook"
        assert stored["webhook_secret"] == "secret123"

    @pytest.mark.asyncio
    async def test_crawl_without_webhook(self, client, mock_db_user, mock_redis, mock_redis_for_jobs, mock_celery_task):
        """Crawl works normally without webhook params."""
        _, job_store = mock_redis_for_jobs

        resp = await client.post("/v1/crawl", json={
            "url": "https://example.com/products",
            "schema": {"name": "string"},
        })
        assert resp.status_code == 200
        job_id = resp.json()["job_id"]

        stored = json.loads(job_store[f"job:{job_id}:status"])
        assert "webhook_url" not in stored


# ---------------------------------------------------------------------------
# Integration tests: pipeline async mode with webhook
# ---------------------------------------------------------------------------

class TestPipelineWebhookIntegration:
    """Test that the pipeline endpoint supports async mode via webhook."""

    @pytest.mark.asyncio
    async def test_pipeline_async_mode(self, client, mock_db_user, mock_redis):
        """Pipeline with webhook_url and extract_from > 3 returns job ID."""
        mock_task = MagicMock()
        mock_task.delay = MagicMock()

        mock_client = MagicMock()
        mock_client.set = AsyncMock()

        with patch("api.routers.pipeline.get_browser_pool", return_value=MagicMock()), \
             patch("api.workers.crawl_worker.pipeline_async_task", mock_task), \
             patch("api.routers.pipeline.get_redis_client", return_value=mock_client):

            resp = await client.post("/v1/pipeline", json={
                "query": "best restaurants",
                "schema": {"name": "str"},
                "extract_from": 5,
                "webhook_url": "https://myapp.com/webhook",
            })

        assert resp.status_code == 200
        data = resp.json()
        assert "job_id" in data
        assert data["status"] == "processing"
        assert "/v1/jobs/" in data["poll_url"]
        mock_task.delay.assert_called_once()

    @pytest.mark.asyncio
    async def test_pipeline_sync_with_webhook_small_extract(self, client, mock_db_user, mock_redis):
        """Pipeline with webhook_url but extract_from <= 3 runs synchronously."""
        fake_search = {
            "query": "test",
            "results": [
                {"title": "Result 1", "url": "https://example.com/1", "snippet": "Test", "source": "google", "position": 1},
            ],
            "meta": {"total_results": 1, "cached": False, "response_time_ms": 100, "engines_used": ["google"]},
        }

        mock_pool = MagicMock()
        mock_pool.render_url = AsyncMock(return_value=("<html><body>Test</body></html>", "Test"))

        fake_result = MagicMock()
        fake_result.data = {"name": "Test"}

        with patch("api.routers.pipeline.execute_search", new_callable=AsyncMock, return_value=fake_search), \
             patch("api.routers.pipeline.get_browser_pool", return_value=mock_pool), \
             patch("api.routers.pipeline.extract", new_callable=AsyncMock, return_value=fake_result), \
             patch("api.routers.pipeline.record_usage_to_db", new_callable=AsyncMock):

            resp = await client.post("/v1/pipeline", json={
                "query": "test",
                "schema": {"name": "str"},
                "extract_from": 2,
                "webhook_url": "https://myapp.com/webhook",
            })

        assert resp.status_code == 200
        data = resp.json()
        # Sync response — has query and results, not job_id
        assert "query" in data
        assert "results" in data

    @pytest.mark.asyncio
    async def test_pipeline_sync_without_webhook(self, client, mock_db_user, mock_redis):
        """Pipeline without webhook always runs synchronously."""
        fake_search = {
            "query": "test",
            "results": [],
            "meta": {"total_results": 0, "cached": False, "response_time_ms": 50, "engines_used": []},
        }

        mock_pool = MagicMock()

        with patch("api.routers.pipeline.execute_search", new_callable=AsyncMock, return_value=fake_search), \
             patch("api.routers.pipeline.get_browser_pool", return_value=mock_pool), \
             patch("api.routers.pipeline.record_usage_to_db", new_callable=AsyncMock):

            resp = await client.post("/v1/pipeline", json={
                "query": "test",
                "schema": {"name": "str"},
                "extract_from": 10,
            })

        assert resp.status_code == 200
        data = resp.json()
        assert "query" in data
        assert "results" in data
