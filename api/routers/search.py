"""Search endpoints — /v1/search, /v1/news, /v1/images, /v1/suggest, /v1/search/ai, /v1/usage."""

import asyncio
import time
from fastapi import APIRouter, Query, Depends, Response, HTTPException
from typing import Literal, Optional

from api.models.search import SearchResponse
from api.services.searxng_client import execute_search, search_multi
from api.services.cache import get_cached, set_cached
from api.services.query_normalizer import normalize_query, reformulate_query
from api.config import get_settings
from api.middleware.auth import get_api_key_user
from api.middleware.rate_limit import (
    check_rate_limit,
    reserve_credits,
    release_credits,
    record_usage_to_db,
)
from api.middleware.metrics import CACHE_HITS, CACHE_REQUESTS, CREDITS_CONSUMED

router = APIRouter(tags=["Search"])


def _set_headers(response: Response, *header_dicts: dict):
    """Set multiple header dicts on the response."""
    for headers in header_dicts:
        for k, v in headers.items():
            response.headers[k] = v


async def _search_with_cache(
    response: Response,
    user_info: dict,
    cache_key: str,
    cache_ttl: int,
    credits: int,
    search_kwargs: dict,
    endpoint: str = "",
    post_process=None,
) -> dict:
    """Common search flow: rate limit -> reserve credits -> cache check -> execute -> cache set.

    Credits are reserved atomically before execution to prevent race conditions
    under concurrent requests. Released on failure.
    """
    rl_headers = await check_rate_limit(user_info)
    credit_headers = await reserve_credits(user_info, credits)
    no_retain = not user_info.get("data_retention", True)

    start = time.monotonic()
    completed = False
    is_cached = False

    try:
        if not no_retain:
            CACHE_REQUESTS.inc()
            cached_result = await get_cached(cache_key)
            if cached_result:
                cached_result["meta"]["cached"] = True
                is_cached = True
                completed = True
                CACHE_HITS.inc()
                CREDITS_CONSUMED.inc(credits)
                _set_headers(response, rl_headers, credit_headers)
                if no_retain:
                    response.headers["X-Data-Retention"] = "none"
                return cached_result

        results = await execute_search(**search_kwargs)

        if post_process:
            results = post_process(results)

        if not no_retain:
            await set_cached(cache_key, results, ttl=cache_ttl)
        completed = True
        CREDITS_CONSUMED.inc(credits)
        _set_headers(response, rl_headers, credit_headers)
        if no_retain:
            response.headers["X-Data-Retention"] = "none"
        return results
    except HTTPException:
        raise
    except Exception:
        await release_credits(user_info, credits)
        raise
    finally:
        if completed:
            elapsed = int((time.monotonic() - start) * 1000)
            asyncio.create_task(
                record_usage_to_db(
                    user_info["api_key_id"], endpoint, credits, is_cached, elapsed,
                    data_retention=not no_retain,
                )
            )


def _compute_tfidf_score(query: str, result: dict) -> float:
    """Simple keyword overlap score between query and result title+snippet."""
    query_terms = set(query.lower().split())
    text = f"{result.get('title', '')} {result.get('snippet', '')}".lower()
    text_words = set(text.split())
    if not query_terms:
        return 0.0
    overlap = query_terms & text_words
    return len(overlap) / len(query_terms)


def _merge_and_dedup_results(result_sets: list[dict], query: str, count: int) -> dict:
    """Merge multiple SearXNG result sets, deduplicate by URL, re-rank by relevance."""
    seen_urls: set[str] = set()
    all_results: list[dict] = []
    all_suggestions: list[str] = []
    all_engines: set[str] = set()
    infobox = None

    for result_set in result_sets:
        if not infobox and result_set.get("infobox"):
            infobox = result_set["infobox"]
        all_suggestions.extend(result_set.get("suggestions", []))
        for engine in result_set.get("meta", {}).get("engines_used", []):
            all_engines.add(engine)
        for r in result_set.get("results", []):
            url = r.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                all_results.append(r)

    # Re-rank by TF-IDF relevance score
    scored = [(r, _compute_tfidf_score(query, r)) for r in all_results]
    scored.sort(key=lambda x: x[1], reverse=True)

    final_results = []
    for i, (r, _) in enumerate(scored[:count]):
        r["position"] = i + 1
        final_results.append(r)

    # Deduplicate suggestions
    seen_sugg: set[str] = set()
    unique_suggestions = []
    for s in all_suggestions:
        if s not in seen_sugg:
            seen_sugg.add(s)
            unique_suggestions.append(s)

    return {
        "query": query,
        "results": final_results,
        "infobox": infobox,
        "suggestions": unique_suggestions[:10],
        "meta": {
            "total_results": len(final_results),
            "cached": False,
            "response_time_ms": 0,
            "engines_used": list(all_engines),
        },
    }


# Depth mode configuration
_DEPTH_CONFIG = {
    "fast": {"timeout": 3.0, "credits": 1},
    "basic": {"timeout": 10.0, "credits": 1},
    "deep": {"timeout": 20.0, "credits": 2},
}


@router.get("/search", response_model=SearchResponse)
async def web_search(
    response: Response,
    q: str = Query(..., min_length=1, max_length=500, description="Search query"),
    count: int = Query(10, ge=1, le=50, description="Results per page"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    country: Optional[str] = Query(None, max_length=5, description="Country code"),
    language: str = Query("en", max_length=10, description="Language code"),
    safesearch: int = Query(1, ge=0, le=2, description="Safe search level"),
    freshness: Optional[str] = Query(None, description="day, week, month, year"),
    depth: Literal["fast", "basic", "deep"] = Query("basic", description="Search depth: fast (3s), basic (10s), deep (20s, 2 credits)"),
    user_info: dict = Depends(get_api_key_user),
):
    """Web search — returns structured results from multiple search engines."""
    settings = get_settings()
    norm_q = normalize_query(q)
    depth_cfg = _DEPTH_CONFIG[depth]
    credits = depth_cfg["credits"]
    cache_key = f"web:{norm_q}:{count}:{offset}:{country}:{language}:{safesearch}:{freshness}:{depth}"

    if depth == "deep":
        # Deep mode: multi-query search with merge + dedup + re-rank
        rl_headers = await check_rate_limit(user_info)
        credit_headers = await reserve_credits(user_info, credits)

        start = time.monotonic()
        completed = False
        is_cached = False

        try:
            CACHE_REQUESTS.inc()
            cached_result = await get_cached(cache_key)
            if cached_result:
                cached_result["meta"]["cached"] = True
                is_cached = True
                completed = True
                CACHE_HITS.inc()
                CREDITS_CONSUMED.inc(credits)
                _set_headers(response, rl_headers, credit_headers)
                return cached_result

            reformulated = reformulate_query(q)
            result_sets = await search_multi(
                queries=[q, reformulated],
                categories=["general"],
                count=count,
                language=language,
                safesearch=safesearch,
                time_range=freshness,
                timeout=depth_cfg["timeout"],
            )

            merged = _merge_and_dedup_results(result_sets, q, count)
            elapsed_ms = int((time.monotonic() - start) * 1000)
            merged["meta"]["response_time_ms"] = elapsed_ms

            await set_cached(cache_key, merged, ttl=settings.cache_ttl_web)
            completed = True
            CREDITS_CONSUMED.inc(credits)
            _set_headers(response, rl_headers, credit_headers)
            return merged
        except HTTPException:
            raise
        except Exception:
            await release_credits(user_info, credits)
            raise
        finally:
            if completed:
                elapsed = int((time.monotonic() - start) * 1000)
                asyncio.create_task(
                    record_usage_to_db(
                        user_info["api_key_id"], "/v1/search", credits, is_cached, elapsed
                    )
                )
    else:
        # Fast and basic modes
        return await _search_with_cache(
            response=response,
            user_info=user_info,
            cache_key=cache_key,
            cache_ttl=settings.cache_ttl_web,
            credits=credits,
            endpoint="/v1/search",
            search_kwargs=dict(
                query=q, categories=["general"], count=count, offset=offset,
                language=language, safesearch=safesearch, time_range=freshness,
                timeout=depth_cfg["timeout"],
            ),
        )


@router.get("/news", response_model=SearchResponse)
async def news_search(
    response: Response,
    q: str = Query(..., min_length=1, max_length=500, description="Search query"),
    count: int = Query(10, ge=1, le=50, description="Results per page"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    language: str = Query("en", max_length=10, description="Language code"),
    freshness: Optional[str] = Query(None, description="day, week, month, year"),
    user_info: dict = Depends(get_api_key_user),
):
    """News search — returns recent news articles."""
    settings = get_settings()
    norm_q = normalize_query(q)
    cache_key = f"news:{norm_q}:{count}:{offset}:{language}:{freshness}"

    return await _search_with_cache(
        response=response,
        user_info=user_info,
        cache_key=cache_key,
        cache_ttl=settings.cache_ttl_news,
        credits=1,
        endpoint="/v1/news",
        search_kwargs=dict(
            query=q, categories=["news"], count=count, offset=offset,
            language=language, time_range=freshness,
        ),
    )


@router.get("/images", response_model=SearchResponse)
async def image_search(
    response: Response,
    q: str = Query(..., min_length=1, max_length=500, description="Search query"),
    count: int = Query(20, ge=1, le=50, description="Results per page"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    safesearch: int = Query(1, ge=0, le=2, description="Safe search level"),
    user_info: dict = Depends(get_api_key_user),
):
    """Image search — returns image results."""
    settings = get_settings()
    norm_q = normalize_query(q)
    cache_key = f"images:{norm_q}:{count}:{offset}:{safesearch}"

    return await _search_with_cache(
        response=response,
        user_info=user_info,
        cache_key=cache_key,
        cache_ttl=settings.cache_ttl_images,
        credits=1,
        endpoint="/v1/images",
        search_kwargs=dict(
            query=q, categories=["images"], count=count, offset=offset,
            safesearch=safesearch,
        ),
    )


def _build_ai_context(results: dict) -> dict:
    """Enrich results with RAG-ready context and numbered sources."""
    top = results.get("results", [])[:5]
    sources = [{"title": r["title"], "url": r["url"], "snippet": r["snippet"]} for r in top]

    context_parts = []
    for i, s in enumerate(sources, 1):
        if s["snippet"]:
            context_parts.append(f"[{i}] {s['title']}: {s['snippet']}")

    results["context"] = "\n\n".join(context_parts)
    results["sources"] = sources
    return results


@router.get("/search/ai", response_model=SearchResponse)
async def ai_search(
    response: Response,
    q: str = Query(..., min_length=1, max_length=500, description="Search query"),
    count: int = Query(10, ge=1, le=50, description="Results per page"),
    language: str = Query("en", max_length=10, description="Language code"),
    freshness: Optional[str] = Query(None, description="day, week, month, year"),
    user_info: dict = Depends(get_api_key_user),
):
    """LLM-optimized search — returns RAG-ready context with numbered sources. Costs 2 credits."""
    settings = get_settings()
    norm_q = normalize_query(q)
    cache_key = f"ai:{norm_q}:{count}:{language}:{freshness}"

    return await _search_with_cache(
        response=response,
        user_info=user_info,
        cache_key=cache_key,
        cache_ttl=settings.cache_ttl_web,
        credits=2,
        endpoint="/v1/search/ai",
        search_kwargs=dict(
            query=q, categories=["general"], count=count,
            language=language, time_range=freshness,
        ),
        post_process=_build_ai_context,
    )


@router.get("/suggest")
async def suggest(
    response: Response,
    q: str = Query(..., min_length=1, max_length=200, description="Query prefix"),
    user_info: dict = Depends(get_api_key_user),
):
    """Autocomplete suggestions."""
    rl_headers = await check_rate_limit(user_info)
    credit_headers = await reserve_credits(user_info, credits=1)

    start = time.monotonic()
    completed = False
    is_cached = False

    try:
        norm_q = normalize_query(q)
        cache_key = f"suggest:{norm_q}"

        CACHE_REQUESTS.inc()
        cached = await get_cached(cache_key)
        if cached:
            is_cached = True
            completed = True
            CACHE_HITS.inc()
            CREDITS_CONSUMED.inc()
            _set_headers(response, rl_headers, credit_headers)
            return cached

        results = await execute_search(query=q, categories=["general"], count=1)
        suggestions = results.get("suggestions", [])
        result = {"query": q, "suggestions": suggestions}

        settings = get_settings()
        await set_cached(cache_key, result, ttl=settings.cache_ttl_suggest)
        completed = True
        CREDITS_CONSUMED.inc()
        _set_headers(response, rl_headers, credit_headers)
        return result
    except HTTPException:
        raise
    except Exception:
        await release_credits(user_info, credits=1)
        raise
    finally:
        if completed:
            elapsed = int((time.monotonic() - start) * 1000)
            asyncio.create_task(
                record_usage_to_db(
                    user_info["api_key_id"], "/v1/suggest", 1, is_cached, elapsed
                )
            )


@router.get("/usage")
async def usage(user_info: dict = Depends(get_api_key_user)):
    """Get current usage and plan info."""
    from datetime import datetime, timezone
    from api.models.user import PLAN_LIMITS
    from api.services.cache import get_counter

    now = datetime.now(timezone.utc)
    month_key = f"usage:{user_info['api_key_id']}:{now.year}:{now.month}"

    used = await get_counter(month_key)
    plan = user_info["plan"]
    limits = PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])

    return {
        "plan": plan,
        "billing_period": f"{now.year}-{now.month:02d}",
        "credits_used": used,
        "credits_limit": limits["monthly_credits"],
        "credits_remaining": max(0, limits["monthly_credits"] - used),
        "rate_limit_per_sec": limits["rate_per_sec"],
    }
