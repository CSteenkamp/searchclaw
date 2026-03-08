"""Agent service — orchestrates search → filter → extract → merge pipeline."""

import asyncio
import logging
from typing import Any

from api.models.agent import AgentResponse, AgentStep, AgentSource
from api.services.browser_pool import get_browser_pool
from api.services.extractor import extract
from api.services.html_cleaner import clean_html, html_to_text
from api.services.query_generator import generate_search_queries
from api.services.searxng_client import execute_search

logger = logging.getLogger(__name__)


def _score_url(title: str, snippet: str, keywords: list[str]) -> float:
    """Score a URL by keyword overlap in title + snippet."""
    text = f"{title} {snippet}".lower()
    if not keywords:
        return 0.0
    matches = sum(1 for kw in keywords if kw.lower() in text)
    return matches / len(keywords)


async def _extract_single(pool: Any, url: str, schema: dict | None) -> dict | str | None:
    """Extract data from a single URL, returning None on failure."""
    try:
        raw_html, page_title = await pool.render_url(url, timeout_ms=20000)
        if schema:
            result = await extract(raw_html, url, schema=schema)
            return result.data
        else:
            cleaned = clean_html(raw_html)
            return html_to_text(cleaned)
    except Exception as e:
        logger.warning("Agent extract failed for %s: %s", url, e)
        return None


async def run_agent(
    prompt: str,
    schema: dict[str, Any] | None = None,
    urls: list[str] | None = None,
    max_credits: int = 10,
    max_sources: int = 5,
) -> AgentResponse:
    """Run the autonomous agent pipeline: search → filter → extract → merge."""
    steps: list[AgentStep] = []
    sources: list[AgentSource] = []
    credits_used = 0

    pool = get_browser_pool()
    if pool is None:
        return AgentResponse(
            success=False, status="failed", error="Browser pool not initialized",
        )

    # --- Phase 1: Search ---
    search_results_all: list[dict] = []
    queries: list[str] = []

    if urls:
        # Use provided seed URLs directly
        for u in urls:
            search_results_all.append({"url": str(u), "title": "", "snippet": ""})
    else:
        queries = generate_search_queries(prompt, max_queries=3)
        for q in queries:
            if credits_used >= max_credits:
                break
            try:
                result = await execute_search(query=q, count=10)
                credits_used += 1  # 1 credit per search
                for r in result.get("results", []):
                    search_results_all.append(r)
            except Exception as e:
                logger.warning("Agent search failed for query '%s': %s", q, e)

    steps.append(AgentStep(
        phase="search",
        queries=queries or None,
        results=len(search_results_all),
    ))

    if not search_results_all:
        return AgentResponse(
            success=False, status="failed",
            error="No search results found",
            credits_used=credits_used, steps=steps,
        )

    # --- Phase 2: Filter ---
    # Extract keywords from prompt for scoring
    from api.services.query_generator import _extract_keywords
    keywords = _extract_keywords(prompt)

    # Deduplicate by URL
    seen_urls: set[str] = set()
    unique_results: list[dict] = []
    for r in search_results_all:
        u = r.get("url", "")
        if u and u not in seen_urls:
            seen_urls.add(u)
            unique_results.append(r)

    # Score and sort
    scored = sorted(
        unique_results,
        key=lambda r: _score_url(r.get("title", ""), r.get("snippet", ""), keywords),
        reverse=True,
    )
    selected = scored[:max_sources]

    steps.append(AgentStep(phase="filter", urls_selected=len(selected)))

    # --- Phase 3: Extract ---
    sem = asyncio.Semaphore(3)
    extract_results: list[tuple[dict, dict | str | None]] = []

    async def _do_extract(result_item: dict) -> tuple[dict, dict | str | None]:
        async with sem:
            data = await _extract_single(pool, result_item["url"], schema)
            return result_item, data

    remaining_credits = max_credits - credits_used
    urls_to_process = selected[:remaining_credits]  # Each extraction costs 1 credit

    tasks = [_do_extract(r) for r in urls_to_process]
    raw_results = await asyncio.gather(*tasks)

    succeeded = 0
    extractions: list[dict | str] = []
    for result_item, data in raw_results:
        credits_used += 1
        if data is not None:
            succeeded += 1
            extractions.append(data)
            sources.append(AgentSource(
                url=result_item["url"],
                title=result_item.get("title") or None,
            ))

    steps.append(AgentStep(
        phase="extract",
        pages_processed=len(urls_to_process),
        pages_succeeded=succeeded,
    ))

    if not extractions:
        return AgentResponse(
            success=False, status="failed",
            error="All extractions failed",
            credits_used=credits_used, steps=steps, sources=sources,
        )

    # --- Phase 4: Merge ---
    if schema:
        # Merge structured results
        merged = _merge_structured(extractions)
        output_type = "structured"
    else:
        # Concatenate markdown with attribution
        parts: list[str] = []
        for i, (ext, src) in enumerate(zip(extractions, sources)):
            parts.append(f"## Source: {src.url}\n\n{ext}")
        merged = "\n\n---\n\n".join(parts)
        output_type = "markdown"

    steps.append(AgentStep(phase="merge", output_type=output_type))

    return AgentResponse(
        success=True,
        status="completed",
        data=merged,
        sources=sources,
        credits_used=credits_used,
        steps=steps,
    )


def _merge_structured(extractions: list[dict | str]) -> dict[str, Any]:
    """Merge multiple structured extraction results, deduplicating arrays."""
    merged: dict[str, Any] = {}
    for ext in extractions:
        if not isinstance(ext, dict):
            continue
        for key, value in ext.items():
            if key not in merged:
                merged[key] = value
            elif isinstance(merged[key], list) and isinstance(value, list):
                # Deduplicate list items by string representation
                existing = {str(item) for item in merged[key]}
                for item in value:
                    if str(item) not in existing:
                        existing.add(str(item))
                        merged[key].append(item)
            elif isinstance(merged[key], dict) and isinstance(value, dict):
                merged[key].update(value)
    return merged
