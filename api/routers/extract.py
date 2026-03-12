"""POST /v1/extract — structured data extraction from URLs."""

import asyncio
import hashlib
import json
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response

from api.middleware.auth import get_api_key_user
from api.middleware.rate_limit import check_rate_limit, reserve_credits, release_credits, record_usage_to_db
from api.models.extraction import ExtractRequest, ExtractResponse, ExtractionMeta
from api.services.browser_pool import get_browser_pool
from api.services.cache import get_cached, set_cached
from api.services.extractor import extract
from api.services.chunker import chunk_text
from api.services.html_cleaner import clean_html, html_to_text
from api.services.proxy_manager import get_proxy_manager, resolve_proxy_tier


def _apply_chunking(resp: ExtractResponse, chunking_config) -> ExtractResponse:
    """Apply chunking to extraction response if enabled."""
    if not chunking_config or not chunking_config.enabled:
        return resp
    # Chunk the data if it's a string
    text = resp.data if isinstance(resp.data, str) else json.dumps(resp.data)
    chunks = chunk_text(
        text,
        max_size=chunking_config.max_chunk_size,
        overlap=chunking_config.overlap,
        strategy=chunking_config.strategy,
    )
    resp.chunks = [
        {"index": c["index"], "text": c["text"], "char_count": c["char_count"], "metadata": c["metadata"]}
        for c in chunks
    ]
    resp.total_chunks = len(chunks)
    return resp

router = APIRouter(tags=["Extract"])


def _make_extract_cache_key(url: str, schema: dict | None, prompt: str | None) -> str:
    """Build a deterministic cache key from url + schema + prompt."""
    parts = url
    if schema:
        parts += json.dumps(schema, sort_keys=True)
    if prompt:
        parts += prompt
    digest = hashlib.sha256(parts.encode()).hexdigest()
    return f"extract:{digest}"


@router.post(
    "/extract",
    response_model=ExtractResponse,
    summary="Extract structured data from a URL",
    description="Render a webpage with a headless browser and extract structured data "
    "matching the provided JSON schema or natural language prompt.",
    responses={
        200: {"description": "Successful extraction"},
        402: {"description": "Insufficient credits"},
        502: {"description": "Failed to render target page"},
        503: {"description": "Browser pool not ready"},
    },
)
async def extract_endpoint(
    req: ExtractRequest,
    response: Response,
    user_info: dict = Depends(get_api_key_user),
) -> ExtractResponse:
    pool = get_browser_pool()
    if pool is None:
        raise HTTPException(503, "Browser pool not initialized")

    try:
        return await asyncio.wait_for(
            _extract_endpoint_inner(req, response, user_info, pool),
            timeout=30,
        )
    except asyncio.TimeoutError:
        raise HTTPException(504, "Request timed out after 30 seconds. The browser service may be unavailable.")


async def _extract_endpoint_inner(
    req: ExtractRequest,
    response: Response,
    user_info: dict,
    pool,
) -> ExtractResponse:
    rl_headers = await check_rate_limit(user_info)
    credit_headers = await reserve_credits(user_info, credits=1)

    start = time.monotonic()
    url = str(req.url)
    completed = False
    is_cached = False
    credits = 1

    try:
        # Check cache
        cache_key = _make_extract_cache_key(url, req.schema_, req.prompt)
        if req.cache:
            cached = await get_cached(cache_key)
            if cached is not None:
                elapsed_ms = int((time.monotonic() - start) * 1000)
                cached["meta"]["cached"] = True
                cached["meta"]["response_time_ms"] = elapsed_ms
                is_cached = True
                completed = True
                for k, v in {**rl_headers, **credit_headers}.items():
                    response.headers[k] = v
                return ExtractResponse(**cached)

        # Resolve proxy
        tier = resolve_proxy_tier(req.proxy, user_info["plan"])
        proxy_url = None
        pm = get_proxy_manager()
        if pm and tier != "none":
            proxy_cfg = pm.get_proxy(tier)
            proxy_url = proxy_cfg.url if proxy_cfg else None
            if tier == "residential":
                credits += 1
                await reserve_credits(user_info, credits=1)

        # Render page
        try:
            raw_html, page_title = await pool.render_url(
                url, wait_for=req.wait_for, timeout_ms=req.timeout_ms,
                proxy_url=proxy_url,
            )
        except Exception as e:
            raise HTTPException(502, f"Failed to render page: {e}")

        # Run extraction pipeline
        try:
            result = await extract(raw_html, url, schema=req.schema_, prompt=req.prompt)
        except RuntimeError:
            cleaned = clean_html(raw_html)
            data: dict[str, Any] | str = html_to_text(cleaned)
            elapsed_ms = int((time.monotonic() - start) * 1000)
            completed = True
            for k, v in {**rl_headers, **credit_headers}.items():
                response.headers[k] = v
            raw_resp = ExtractResponse(
                url=url,
                data=data,
                meta=ExtractionMeta(
                    cached=False, response_time_ms=elapsed_ms, credits_used=1,
                    extraction_method="raw", page_title=page_title,
                ),
            )
            return _apply_chunking(raw_resp, req.chunking)

        elapsed_ms = int((time.monotonic() - start) * 1000)
        credits = 1 if result.extraction_method == "rule" else 2

        resp = ExtractResponse(
            url=url,
            data=result.data,
            meta=ExtractionMeta(
                cached=False, response_time_ms=elapsed_ms, credits_used=credits,
                extraction_method=result.extraction_method,
                model_used=result.model_used,
                tokens_used=result.tokens_used or None,
                page_title=page_title,
            ),
        )

        resp = _apply_chunking(resp, req.chunking)

        if req.cache:
            await set_cached(cache_key, resp.model_dump())

        completed = True
        for k, v in {**rl_headers, **credit_headers}.items():
            response.headers[k] = v
        return resp

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
                    user_info["api_key_id"], "/v1/extract", credits, is_cached, elapsed
                )
            )
