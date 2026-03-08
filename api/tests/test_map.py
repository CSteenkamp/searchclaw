"""Tests for /v1/map endpoint — URL discovery."""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch, MagicMock

from api.services.map_service import (
    _same_domain,
    _normalize_url,
    _extract_links,
    _extract_title,
    discover_urls,
)


# --- Unit tests for helper functions ---

class TestSameDomain:
    def test_same_domain_exact(self):
        assert _same_domain("example.com", "https://example.com/page", False)

    def test_same_domain_rejects_different(self):
        assert not _same_domain("example.com", "https://other.com/page", False)

    def test_subdomain_rejected_without_flag(self):
        assert not _same_domain("example.com", "https://docs.example.com/page", False)

    def test_subdomain_accepted_with_flag(self):
        assert _same_domain("example.com", "https://docs.example.com/page", True)

    def test_empty_host(self):
        assert not _same_domain("example.com", "/relative/path", False)


class TestNormalizeUrl:
    def test_strips_trailing_slash(self):
        assert _normalize_url("https://example.com/page/") == "https://example.com/page"

    def test_preserves_query(self):
        assert _normalize_url("https://example.com/page?a=1") == "https://example.com/page?a=1"

    def test_strips_fragment(self):
        assert _normalize_url("https://example.com/page#section") == "https://example.com/page"

    def test_root_path(self):
        assert _normalize_url("https://example.com/") == "https://example.com/"
        assert _normalize_url("https://example.com") == "https://example.com/"


class TestExtractLinks:
    def test_extracts_absolute_links(self):
        html = '<a href="https://example.com/page1">Link</a><a href="https://example.com/page2">Link2</a>'
        links = _extract_links(html, "https://example.com")
        assert "https://example.com/page1" in links
        assert "https://example.com/page2" in links

    def test_resolves_relative_links(self):
        html = '<a href="/about">About</a>'
        links = _extract_links(html, "https://example.com/page")
        assert "https://example.com/about" in links

    def test_skips_mailto_and_javascript(self):
        html = '<a href="mailto:test@test.com">Mail</a><a href="javascript:void(0)">JS</a>'
        links = _extract_links(html, "https://example.com")
        assert len(links) == 0

    def test_skips_fragments(self):
        html = '<a href="#top">Top</a>'
        links = _extract_links(html, "https://example.com")
        assert len(links) == 0


class TestExtractTitle:
    def test_extracts_title(self):
        html = "<html><head><title>My Page</title></head></html>"
        assert _extract_title(html) == "My Page"

    def test_no_title(self):
        html = "<html><body>Content</body></html>"
        assert _extract_title(html) is None

    def test_strips_whitespace(self):
        html = "<title>  Spaced Title  </title>"
        assert _extract_title(html) == "Spaced Title"


# --- Integration tests for discover_urls ---

@pytest.mark.asyncio
async def test_discover_urls_with_mock_crawl(mock_redis):
    """Test BFS discovery with mock HTML pages."""
    pages = {
        "https://example.com/": (
            200,
            "text/html",
            '<html><head><title>Home</title></head><body>'
            '<a href="/about">About</a><a href="/contact">Contact</a></body></html>',
        ),
        "https://example.com/about": (
            200,
            "text/html",
            '<html><head><title>About</title></head><body>'
            '<a href="/team">Team</a></body></html>',
        ),
        "https://example.com/contact": (
            200,
            "text/html",
            '<html><head><title>Contact</title></head><body>Contact us</body></html>',
        ),
        "https://example.com/team": (
            200,
            "text/html",
            '<html><head><title>Team</title></head><body>Our team</body></html>',
        ),
        "https://example.com/robots.txt": (200, "text/plain", "User-agent: *\nAllow: /"),
        "https://example.com/sitemap.xml": (404, "text/html", "Not found"),
    }

    async def mock_get(url, **kwargs):
        key = str(url).rstrip("/") if str(url) != "https://example.com/" else str(url)
        # Normalize for lookup
        for page_url, (status, ct, body) in pages.items():
            if str(url).rstrip("/") == page_url.rstrip("/") or str(url) == page_url:
                resp = MagicMock()
                resp.status_code = status
                resp.headers = {"content-type": ct}
                resp.text = body
                return resp
        resp = MagicMock()
        resp.status_code = 404
        resp.headers = {"content-type": "text/html"}
        resp.text = "Not found"
        return resp

    mock_client = AsyncMock()
    mock_client.get = mock_get
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("api.services.map_service.httpx.AsyncClient", return_value=mock_client):
        result = await discover_urls(
            url="https://example.com/",
            max_pages=100,
            ignore_sitemap=False,
            limit=50,
        )

    assert result["success"] is True
    assert result["total_discovered"] >= 3
    urls = [u["url"] for u in result["urls"]]
    assert any("about" in u for u in urls)
    assert any("contact" in u for u in urls)


@pytest.mark.asyncio
async def test_url_deduplication(mock_redis):
    """Test that duplicate URLs are deduplicated."""
    html = (
        '<html><head><title>Home</title></head><body>'
        '<a href="/page">Link1</a>'
        '<a href="/page">Link2</a>'
        '<a href="/page/">Link3</a>'
        '</body></html>'
    )

    async def mock_get(url, **kwargs):
        resp = MagicMock()
        if "robots.txt" in str(url):
            resp.status_code = 404
        elif "sitemap.xml" in str(url):
            resp.status_code = 404
        else:
            resp.status_code = 200
            resp.headers = {"content-type": "text/html"}
            resp.text = html
        resp.headers = resp.headers if hasattr(resp, "headers") and isinstance(resp.headers, dict) else {"content-type": "text/html"}
        return resp

    mock_client = AsyncMock()
    mock_client.get = mock_get
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("api.services.map_service.httpx.AsyncClient", return_value=mock_client):
        result = await discover_urls(
            url="https://example.com/",
            max_pages=100,
            ignore_sitemap=True,
            limit=50,
        )

    # /page and /page/ should be deduplicated
    page_urls = [u["url"] for u in result["urls"] if "page" in u["url"]]
    assert len(page_urls) <= 1


@pytest.mark.asyncio
async def test_search_filter(mock_redis):
    """Test that search parameter filters URLs."""
    html = (
        '<html><head><title>Home</title></head><body>'
        '<a href="/docs/api">API Docs</a>'
        '<a href="/blog/post">Blog Post</a>'
        '</body></html>'
    )

    async def mock_get(url, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        resp.headers = {"content-type": "text/html"}
        resp.text = html
        if "robots" in str(url) or "sitemap" in str(url):
            resp.status_code = 404
        return resp

    mock_client = AsyncMock()
    mock_client.get = mock_get
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("api.services.map_service.httpx.AsyncClient", return_value=mock_client):
        result = await discover_urls(
            url="https://example.com/",
            max_pages=100,
            search="docs",
            ignore_sitemap=True,
            limit=50,
        )

    urls = [u["url"] for u in result["urls"]]
    for u in urls:
        assert "docs" in u.lower() or "home" in u.lower()


@pytest.mark.asyncio
async def test_max_pages_cap(mock_redis):
    """Test that max_pages limits the number of discovered pages."""
    # Generate HTML with many links
    links = "".join(f'<a href="/page{i}">Page {i}</a>' for i in range(50))
    html = f"<html><head><title>Home</title></head><body>{links}</body></html>"

    async def mock_get(url, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        resp.headers = {"content-type": "text/html"}
        resp.text = html
        if "robots" in str(url) or "sitemap" in str(url):
            resp.status_code = 404
        return resp

    mock_client = AsyncMock()
    mock_client.get = mock_get
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("api.services.map_service.httpx.AsyncClient", return_value=mock_client):
        result = await discover_urls(
            url="https://example.com/",
            max_pages=5,
            ignore_sitemap=True,
            limit=50,
        )

    assert result["total_discovered"] <= 5


@pytest.mark.asyncio
async def test_map_endpoint_credits(client, mock_db_user, mock_redis):
    """Test that map endpoint charges 1 credit."""
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    async def mock_get(url, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        resp.headers = {"content-type": "text/html"}
        resp.text = "<html><head><title>Test</title></head><body>Hello</body></html>"
        if "robots" in str(url) or "sitemap" in str(url):
            resp.status_code = 404
        return resp

    mock_client.get = mock_get

    with patch("api.services.map_service.httpx.AsyncClient", return_value=mock_client):
        resp = await client.post("/v1/map", json={"url": "https://example.com/"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["credits_used"] == 1
    assert "X-RateLimit-Limit" in resp.headers


@pytest.mark.asyncio
async def test_sitemap_parsing(mock_redis):
    """Test sitemap XML parsing."""
    from api.services.map_service import _fetch_sitemap

    sitemap_xml = """<?xml version="1.0" encoding="UTF-8"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
        <url><loc>https://example.com/page1</loc></url>
        <url><loc>https://example.com/page2</loc></url>
        <url><loc>https://example.com/page3</loc></url>
    </urlset>"""

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = sitemap_xml

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)

    urls = await _fetch_sitemap(mock_client, "https://example.com/sitemap.xml", 100)
    assert len(urls) == 3
    assert "https://example.com/page1" in urls
    assert "https://example.com/page2" in urls
    assert "https://example.com/page3" in urls
