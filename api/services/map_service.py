"""URL discovery service — sitemap parsing + BFS crawl."""

import hashlib
import re
import xml.etree.ElementTree as ET
from collections import deque
from typing import Optional
from urllib.parse import urljoin, urlparse

import httpx

from api.services.cache import get_cached, set_cached

_TIMEOUT = 5.0
_CACHE_TTL = 3600  # 1 hour


def _same_domain(base_host: str, url: str, include_subdomains: bool) -> bool:
    """Check if a URL belongs to the same domain (optionally including subdomains)."""
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if not host:
        return False
    if include_subdomains:
        return host == base_host or host.endswith(f".{base_host}")
    return host == base_host


def _normalize_url(url: str) -> str:
    """Normalize a URL for deduplication (strip fragment, trailing slash)."""
    parsed = urlparse(url)
    path = parsed.path.rstrip("/") or "/"
    normalized = f"{parsed.scheme}://{parsed.netloc}{path}"
    if parsed.query:
        normalized += f"?{parsed.query}"
    return normalized


async def _fetch_robots_txt(client: httpx.AsyncClient, base_url: str) -> list[str]:
    """Parse robots.txt for sitemap references."""
    parsed = urlparse(base_url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    sitemaps = []
    try:
        resp = await client.get(robots_url, timeout=_TIMEOUT)
        if resp.status_code == 200:
            for line in resp.text.splitlines():
                line = line.strip()
                if line.lower().startswith("sitemap:"):
                    sitemap_url = line.split(":", 1)[1].strip()
                    sitemaps.append(sitemap_url)
    except Exception:
        pass
    return sitemaps


async def _fetch_sitemap(
    client: httpx.AsyncClient, sitemap_url: str, max_urls: int
) -> list[str]:
    """Parse a sitemap XML (including nested sitemaps) and return URLs."""
    urls: list[str] = []
    try:
        resp = await client.get(sitemap_url, timeout=_TIMEOUT)
        if resp.status_code != 200:
            return urls
        root = ET.fromstring(resp.text)
    except Exception:
        return urls

    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}

    # Check for sitemap index (nested sitemaps)
    for sitemap_el in root.findall(".//sm:sitemap/sm:loc", ns):
        if len(urls) >= max_urls:
            break
        nested = await _fetch_sitemap(client, sitemap_el.text.strip(), max_urls - len(urls))
        urls.extend(nested)

    # Regular URL entries
    for url_el in root.findall(".//sm:url/sm:loc", ns):
        if len(urls) >= max_urls:
            break
        urls.append(url_el.text.strip())

    return urls


def _extract_links(html: str, page_url: str) -> list[str]:
    """Extract href links from HTML."""
    links = []
    for match in re.finditer(r'<a\s+[^>]*href=["\']([^"\']+)["\']', html, re.IGNORECASE):
        href = match.group(1)
        if href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        absolute = urljoin(page_url, href)
        links.append(absolute)
    return links


def _extract_title(html: str) -> Optional[str]:
    """Extract <title> from HTML."""
    match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(1).strip()
    return None


async def discover_urls(
    url: str,
    max_pages: int = 100,
    include_subdomains: bool = False,
    search: Optional[str] = None,
    ignore_sitemap: bool = False,
    limit: int = 50,
) -> dict:
    """Discover URLs on a domain via sitemap + BFS crawl.

    Returns a dict matching MapResponse structure.
    """
    # Check cache
    cache_key_input = f"map:{url}:{max_pages}:{include_subdomains}:{ignore_sitemap}"
    cache_key = f"map:{hashlib.sha256(cache_key_input.encode()).hexdigest()}"
    cached = await get_cached(cache_key)
    if cached is not None:
        # Apply search filter and limit on cached results
        result_urls = cached.get("urls", [])
        if search:
            term = search.lower()
            result_urls = [
                u for u in result_urls
                if term in u["url"].lower() or (u.get("title") and term in u["title"].lower())
            ]
        return {
            "success": True,
            "url": url,
            "total_discovered": cached["total_discovered"],
            "urls": result_urls[:limit],
            "credits_used": 1,
        }

    parsed = urlparse(url)
    base_host = parsed.hostname or ""
    discovered: dict[str, dict] = {}  # url -> {title, source}

    async with httpx.AsyncClient(
        timeout=_TIMEOUT,
        limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        follow_redirects=True,
    ) as client:
        # Step 1 & 2: Sitemap discovery
        if not ignore_sitemap:
            sitemap_urls_to_try = [f"{parsed.scheme}://{parsed.netloc}/sitemap.xml"]
            robots_sitemaps = await _fetch_robots_txt(client, url)
            sitemap_urls_to_try.extend(robots_sitemaps)

            for sitemap_url in sitemap_urls_to_try:
                if len(discovered) >= max_pages:
                    break
                sitemap_entries = await _fetch_sitemap(
                    client, sitemap_url, max_pages - len(discovered)
                )
                for entry_url in sitemap_entries:
                    norm = _normalize_url(entry_url)
                    if norm not in discovered and _same_domain(base_host, norm, include_subdomains):
                        discovered[norm] = {"title": None, "source": "sitemap"}

        # Step 3: BFS crawl
        queue: deque[str] = deque([_normalize_url(url)])
        visited: set[str] = set()

        while queue and len(discovered) < max_pages:
            current_url = queue.popleft()
            if current_url in visited:
                continue
            visited.add(current_url)

            try:
                resp = await client.get(current_url, timeout=_TIMEOUT)
                if resp.status_code != 200:
                    continue
                content_type = resp.headers.get("content-type", "")
                if "text/html" not in content_type:
                    continue
                html = resp.text
            except Exception:
                continue

            title = _extract_title(html)

            norm_current = _normalize_url(current_url)
            if norm_current not in discovered:
                discovered[norm_current] = {"title": title, "source": "crawl"}
            elif discovered[norm_current]["title"] is None and title:
                discovered[norm_current]["title"] = title

            # Extract and enqueue links
            links = _extract_links(html, current_url)
            for link in links:
                norm_link = _normalize_url(link)
                if norm_link not in visited and _same_domain(base_host, norm_link, include_subdomains):
                    queue.append(norm_link)

    # Build result
    all_urls = [
        {"url": u, "title": info["title"], "source": info["source"]}
        for u, info in discovered.items()
    ]

    # Cache full results (before filtering)
    await set_cached(cache_key, {"total_discovered": len(all_urls), "urls": all_urls}, ttl=_CACHE_TTL)

    # Apply search filter
    if search:
        term = search.lower()
        all_urls = [
            u for u in all_urls
            if term in u["url"].lower() or (u.get("title") and term in u["title"].lower())
        ]

    return {
        "success": True,
        "url": url,
        "total_discovered": len(discovered),
        "urls": all_urls[:limit],
        "credits_used": 1,
    }
