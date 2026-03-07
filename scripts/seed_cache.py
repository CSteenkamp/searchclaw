#!/usr/bin/env python3
"""Cache pre-warming script for SearchClaw.

Fetches trending queries from Google Trends RSS feed and/or uses hardcoded
popular tech queries, then sends them through the SearchClaw API to warm
the Redis cache.

Designed to run as a cron job (e.g., every 2 hours).

Environment variables:
    SEARCHCLAW_API_URL:  Base URL of SearchClaw API (default: http://localhost:8000)
    SEARCHCLAW_API_KEY:  API key for authentication

Usage:
    seed_cache.py [--queries N] [--category CATEGORY] [--delay SECONDS]
    seed_cache.py --trends               # Include Google Trends
    seed_cache.py --file queries.txt      # Load from file
    seed_cache.py --dry-run               # Preview without sending
"""

import argparse
import json
import logging
import os
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("seed_cache")

API_URL = os.environ.get("SEARCHCLAW_API_URL", "http://localhost:8000")
API_KEY = os.environ.get("SEARCHCLAW_API_KEY", "")

# Popular tech and general queries for cache warming
DEFAULT_QUERIES = [
    # Programming & DevOps
    "python tutorial",
    "javascript array methods",
    "docker compose example",
    "kubernetes tutorial",
    "git rebase vs merge",
    "react hooks tutorial",
    "typescript generics",
    "rust vs go",
    "postgresql vs mysql",
    "redis cache tutorial",
    "nginx reverse proxy",
    "linux commands cheat sheet",
    "bash scripting guide",
    "css flexbox guide",
    "html table",
    "sql join types",
    "api rest best practices",
    "graphql vs rest",
    "microservices architecture",
    "ci cd pipeline",
    # AI & ML
    "chatgpt alternatives",
    "llm fine tuning",
    "rag retrieval augmented generation",
    "vector database comparison",
    "langchain tutorial",
    "openai api",
    "stable diffusion",
    "machine learning tutorial",
    "neural network explained",
    "transformer architecture",
    # General tech
    "best programming language 2025",
    "how to learn coding",
    "web development roadmap",
    "cloud computing basics",
    "cybersecurity best practices",
    "agile methodology",
    "software design patterns",
    "system design interview",
    "data structures and algorithms",
    "open source projects",
    # Common searches
    "weather today",
    "stock market today",
    "latest news",
    "exchange rate usd",
    "time zones",
    "unit converter",
    "calculator online",
    "translate english to spanish",
    "world population",
    "distance between cities",
]


def fetch_google_trends() -> list[str]:
    """Fetch trending searches from Google Trends RSS feed (no dependencies)."""
    try:
        url = "https://trends.google.com/trends/trendingsearches/daily/rss?geo=US"
        req = Request(url, headers={"User-Agent": "SearchClaw/1.0"})
        with urlopen(req, timeout=10) as resp:
            content = resp.read().decode("utf-8")

        queries = []
        in_item = False
        for line in content.splitlines():
            stripped = line.strip()
            if "<item>" in stripped:
                in_item = True
            elif "</item>" in stripped:
                in_item = False
            elif in_item and "<title>" in stripped:
                title = stripped.replace("<title>", "").replace("</title>", "").strip()
                if title and title != "Daily Search Trends":
                    queries.append(title)

        if queries:
            log.info("Fetched %d trending queries from Google Trends", len(queries))
            return queries
    except Exception as e:
        log.warning("Could not fetch Google Trends: %s", e)

    return []


def search_query(query: str, category: str = "general") -> dict:
    """Send a search query to the SearchClaw API."""
    from urllib.parse import quote

    url = f"{API_URL}/v1/search?q={quote(query)}&category={quote(category)}"

    headers = {"Accept": "application/json"}
    if API_KEY:
        headers["X-API-Key"] = API_KEY

    req = Request(url, headers=headers)

    try:
        with urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            meta = data.get("meta", {})
            return {
                "query": query,
                "status": "ok",
                "cached": meta.get("cached", False),
                "results": meta.get("total_results", 0),
                "time_ms": meta.get("response_time_ms", 0),
            }
    except HTTPError as e:
        return {"query": query, "status": "error", "code": e.code, "reason": str(e.reason)}
    except URLError as e:
        return {"query": query, "status": "error", "reason": str(e.reason)}
    except Exception as e:
        return {"query": query, "status": "error", "reason": str(e)}


def load_queries_from_file(filepath: str) -> list[str]:
    """Load queries from a text file (one per line)."""
    with open(filepath) as f:
        return [line.strip() for line in f if line.strip() and not line.startswith("#")]


def main() -> None:
    parser = argparse.ArgumentParser(description="Warm the SearchClaw Redis cache")
    parser.add_argument("--queries", type=int, default=50, help="Max number of queries (default: 50)")
    parser.add_argument("--category", default="general", help="Search category (default: general)")
    parser.add_argument("--delay", type=float, default=0.5, help="Delay between queries in seconds (default: 0.5)")
    parser.add_argument("--file", help="Load queries from a text file (one per line)")
    parser.add_argument("--trends", action="store_true", help="Include Google Trends queries")
    parser.add_argument("--dry-run", action="store_true", help="Preview queries without sending them")
    args = parser.parse_args()

    if not API_KEY and not args.dry_run:
        log.warning("SEARCHCLAW_API_KEY not set — requests may be rejected")

    # Build query list
    queries: list[str] = []

    if args.file:
        queries.extend(load_queries_from_file(args.file))
        log.info("Loaded %d queries from %s", len(queries), args.file)

    if args.trends:
        queries.extend(fetch_google_trends())

    if not queries:
        queries = DEFAULT_QUERIES.copy()
        log.info("Using %d default queries", len(queries))

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique_queries: list[str] = []
    for q in queries:
        q_lower = q.lower().strip()
        if q_lower not in seen:
            seen.add(q_lower)
            unique_queries.append(q)
    queries = unique_queries[: args.queries]

    log.info(
        "Warming cache: %d queries, category=%s, delay=%.1fs",
        len(queries), args.category, args.delay,
    )
    log.info("API URL: %s", API_URL)

    if args.dry_run:
        log.info("DRY RUN — queries that would be sent:")
        for i, q in enumerate(queries, 1):
            log.info("  [%d] %s", i, q)
        return

    stats = {"ok": 0, "cached": 0, "errors": 0, "total_time_ms": 0}

    for i, query in enumerate(queries, 1):
        result = search_query(query, args.category)

        if result["status"] == "ok":
            stats["ok"] += 1
            stats["total_time_ms"] += result.get("time_ms", 0)
            if result.get("cached"):
                stats["cached"] += 1
            log.info(
                "[%d/%d] OK: %r — %d results, %dms%s",
                i, len(queries), query,
                result.get("results", 0),
                result.get("time_ms", 0),
                " (cached)" if result.get("cached") else "",
            )
        else:
            stats["errors"] += 1
            log.warning(
                "[%d/%d] ERROR: %r — %s",
                i, len(queries), query,
                result.get("reason", result.get("code", "unknown")),
            )

        if i < len(queries):
            time.sleep(args.delay)

    # Summary
    log.info("--- Cache Warm Summary ---")
    log.info("Total queries: %d", len(queries))
    log.info("Successful: %d", stats["ok"])
    log.info("Already cached: %d", stats["cached"])
    log.info("Errors: %d", stats["errors"])
    if stats["ok"] > 0:
        log.info("Avg response time: %.0fms", stats["total_time_ms"] / stats["ok"])


if __name__ == "__main__":
    main()
