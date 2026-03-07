"""Tests for POST /v1/pipeline — search + extract combo endpoint."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestPipelineEndpoint:
    """Pipeline endpoint tests."""

    @pytest.mark.asyncio
    async def test_pipeline_success(self, client, mock_db_user, mock_redis):
        """Pipeline returns search + extraction results."""
        fake_search = {
            "query": "best restaurants",
            "results": [
                {"title": "Restaurant A", "url": "https://example.com/a", "snippet": "Great food", "source": "google", "position": 1},
                {"title": "Restaurant B", "url": "https://example.com/b", "snippet": "Amazing", "source": "bing", "position": 2},
            ],
            "meta": {"total_results": 2, "cached": False, "response_time_ms": 100, "engines_used": ["google"]},
        }

        mock_pool = MagicMock()
        mock_pool.render_url = AsyncMock(return_value=("<html><body>Test</body></html>", "Test Page"))

        fake_extraction_result = MagicMock()
        fake_extraction_result.data = {"name": "Restaurant A", "rating": 4.5}
        fake_extraction_result.extraction_method = "rule"

        with patch("api.routers.pipeline.execute_search", new_callable=AsyncMock, return_value=fake_search), \
             patch("api.routers.pipeline.get_browser_pool", return_value=mock_pool), \
             patch("api.routers.pipeline.extract", new_callable=AsyncMock, return_value=fake_extraction_result), \
             patch("api.routers.pipeline.record_usage_to_db", new_callable=AsyncMock):

            resp = await client.post("/v1/pipeline", json={
                "query": "best restaurants",
                "schema": {"name": "str", "rating": "float"},
                "extract_from": 2,
            })

        assert resp.status_code == 200
        data = resp.json()
        assert data["query"] == "best restaurants"
        assert len(data["results"]) == 2
        assert data["results"][0]["extracted_data"] == {"name": "Restaurant A", "rating": 4.5}
        assert data["meta"]["search_credits"] == 1
        assert data["meta"]["extract_credits"] == 2
        assert data["meta"]["total_credits"] == 3

    @pytest.mark.asyncio
    async def test_pipeline_partial_failure(self, client, mock_db_user, mock_redis):
        """Pipeline handles partial extraction failures gracefully."""
        fake_search = {
            "query": "test",
            "results": [
                {"title": "Good Site", "url": "https://example.com/good", "snippet": "Works", "source": "google", "position": 1},
                {"title": "Bad Site", "url": "https://example.com/bad", "snippet": "Fails", "source": "bing", "position": 2},
            ],
            "meta": {"total_results": 2, "cached": False, "response_time_ms": 50, "engines_used": ["google"]},
        }

        mock_pool = MagicMock()
        call_count = 0

        async def mock_render(url, **kwargs):
            nonlocal call_count
            call_count += 1
            if "bad" in url:
                raise Exception("Connection timeout")
            return ("<html><body>Content</body></html>", "Good Page")

        mock_pool.render_url = mock_render

        fake_result = MagicMock()
        fake_result.data = {"name": "Good"}
        fake_result.extraction_method = "rule"

        with patch("api.routers.pipeline.execute_search", new_callable=AsyncMock, return_value=fake_search), \
             patch("api.routers.pipeline.get_browser_pool", return_value=mock_pool), \
             patch("api.routers.pipeline.extract", new_callable=AsyncMock, return_value=fake_result), \
             patch("api.routers.pipeline.record_usage_to_db", new_callable=AsyncMock):

            resp = await client.post("/v1/pipeline", json={
                "query": "test",
                "schema": {"name": "str"},
                "extract_from": 2,
            })

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["results"]) == 2

        # One succeeded, one failed
        success = [r for r in data["results"] if r["extracted_data"] is not None]
        failed = [r for r in data["results"] if r["error"] is not None]
        assert len(success) == 1
        assert len(failed) == 1
        assert "Connection timeout" in failed[0]["error"]

        # Credit accounting: 1 search + 1 successful extraction
        assert data["meta"]["search_credits"] == 1
        assert data["meta"]["extract_credits"] == 1
        assert data["meta"]["total_credits"] == 2

    @pytest.mark.asyncio
    async def test_pipeline_no_browser_pool(self, client, mock_db_user, mock_redis):
        """Pipeline returns 503 if browser pool not available."""
        with patch("api.routers.pipeline.get_browser_pool", return_value=None):
            resp = await client.post("/v1/pipeline", json={
                "query": "test",
                "schema": {"name": "str"},
            })

        assert resp.status_code == 503

    @pytest.mark.asyncio
    async def test_pipeline_no_search_results(self, client, mock_db_user, mock_redis):
        """Pipeline handles empty search results."""
        fake_search = {
            "query": "obscure query",
            "results": [],
            "meta": {"total_results": 0, "cached": False, "response_time_ms": 50, "engines_used": []},
        }

        mock_pool = MagicMock()

        with patch("api.routers.pipeline.execute_search", new_callable=AsyncMock, return_value=fake_search), \
             patch("api.routers.pipeline.get_browser_pool", return_value=mock_pool), \
             patch("api.routers.pipeline.record_usage_to_db", new_callable=AsyncMock):

            resp = await client.post("/v1/pipeline", json={
                "query": "obscure query",
                "schema": {"name": "str"},
                "extract_from": 3,
            })

        assert resp.status_code == 200
        data = resp.json()
        assert data["results"] == []
        assert data["meta"]["search_credits"] == 1
        assert data["meta"]["extract_credits"] == 0
        assert data["meta"]["total_credits"] == 1

    @pytest.mark.asyncio
    async def test_pipeline_requires_schema(self, client, mock_db_user, mock_redis):
        """Pipeline requires schema field."""
        with patch("api.routers.pipeline.get_browser_pool", return_value=MagicMock()):
            resp = await client.post("/v1/pipeline", json={
                "query": "test",
            })

        assert resp.status_code == 422
