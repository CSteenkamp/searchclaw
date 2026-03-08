"""Search endpoints — /v1/search, /v1/news, /v1/images, /v1/suggest, /v1/search/ai, /v1/usage."""

import asyncio
import time
from fastapi import APIRouter, Query, Depends, Response, HTTPException
from typing import Optional

from api.models.search import SearchResponse
from api.services.searxng_client import execute_search
from api.services.cache import get_cached, set_cached
from api.services.query_normalizer import normalize_query
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

        results = await execute_search(**search_kwargs)

        if post_process:
            results = post_process(results)

        await set_cached(cache_key, results, ttl=cache_ttl)
        completed = True
        CREDITS_CONSUMED.inc(credits)
        _set_headers(response, rl_headers, credit_headers)
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
                    user_info["api_key_id"], endpoint, credits, is_cached, elapsed
                )
            )


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
    user_info: dict = Depends(get_api_key_user),
):
    """Web search — returns structured results from multiple search engines."""
    settings = get_settings()
    norm_q = normalize_query(q)
    cache_key = f"web:{norm_q}:{count}:{offset}:{country}:{language}:{safesearch}:{freshness}"

    return await _search_with_cache(
        response=response,
        user_info=user_info,
        cache_key=cache_key,
        cache_ttl=settings.cache_ttl_web,
        credits=1,
        endpoint="/v1/search",
        search_kwargs=dict(
            query=q, categories=["general"], count=count, offset=offset,
            language=language, safesearch=safesearch, time_range=freshness,
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
