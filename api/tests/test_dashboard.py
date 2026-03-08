"""Tests for dashboard static pages."""

import pytest


class TestDashboardPages:
    """Dashboard pages serve correctly."""

    @pytest.mark.asyncio
    async def test_index_page(self, client):
        """Landing page serves and contains SearchClaw branding."""
        resp = await client.get("/index.html")
        assert resp.status_code == 200
        text = resp.text
        assert "SearchClaw" in text
        assert "Search, Extract, Crawl" in text

    @pytest.mark.asyncio
    async def test_docs_page(self, client):
        """Docs page serves correctly."""
        resp = await client.get("/docs.html")
        assert resp.status_code == 200
        assert "SearchClaw" in resp.text

    @pytest.mark.asyncio
    async def test_playground_page(self, client):
        """Playground page serves correctly."""
        resp = await client.get("/playground.html")
        assert resp.status_code == 200
        assert "SearchClaw" in resp.text

    @pytest.mark.asyncio
    async def test_dashboard_page(self, client):
        """Dashboard page serves correctly."""
        resp = await client.get("/dashboard.html")
        assert resp.status_code == 200
        text = resp.text
        assert "SearchClaw" in text
        assert "Dashboard" in text
        assert "API Keys" in text
