"""POST /v1/pipeline — search + extract in one call."""

import asyncio
import json
import logging
import time
import uuid
from typing import Any, Union

from fastapi import APIRouter, Depends, HTTPException, Response

from api.middleware.auth import get_api_key_user
from api.middleware.rate_limit import check_rate_limit, reserve_credits, release_credits, record_usage_to_db
from api.models.job import CrawlResponse
from api.models.pipeline import PipelineRequest, PipelineResponse, PipelineResultItem, PipelineMeta
from api.services.browser_pool import get_browser_pool
from api.services.cache import get_redis_client
from api.services.extractor import extract
from api.services.html_cleaner import clean_html, html_to_text
from api.services.searxng_client import execute_search

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Pipeline"])


async def _extract_single_url(
    pool: Any,
    url: str,
    title: str,
    schema: dict[str, Any],
    timeout_ms: int,
) -> PipelineResultItem:
    """Extract structured data from a single URL, returning errors gracefully."""
    try:
        raw_html, page_title = await pool.render_url(
            url, wait_for="networkidle", timeout_ms=timeout_ms
        )

        try:
            result = await extract(raw_html, url, schema=schema)
            return PipelineResultItem(
                url=url,
                title=page_title or title,
                extracted_data=result.data,
            )
        except RuntimeError:
            cleaned = clean_html(raw_html)
            text = html_to_text(cleaned)
            return PipelineResultItem(
                url=url,
                title=page_title or title,
                extracted_data={"raw_text": text},
            )
    except Exception as e:
        return PipelineResultItem(
            url=url,
            title=title,
            extracted_data=None,
            error=str(e),
        )


async def _pipeline_async(req: PipelineRequest, user_info: dict) -> CrawlResponse:
    """Dispatch pipeline as an async job with webhook delivery."""
    from api.workers.crawl_worker import pipeline_async_task

    total_credits = 1 + req.extract_from
    await check_rate_limit(user_info)
    await reserve_credits(user_info, credits=total_credits)

    job_id = f"job_{uuid.uuid4().hex[:12]}"

    redis_client = get_redis_client()
    if redis_client:
        job_data = {
            "status": "queued",
            "webhook_url": req.webhook_url,
        }
        if req.webhook_secret:
            job_data["webhook_secret"] = req.webhook_secret
        await redis_client.set(f"job:{job_id}:status", json.dumps(job_data), ex=3600)

    pipeline_async_task.delay(
        job_id=job_id,
        query=req.query,
        schema=req.schema_,
        max_results=req.max_results,
        extract_from=req.extract_from,
        language=req.search_params.language,
        timeout=req.timeout,
        webhook_url=req.webhook_url,
        webhook_secret=req.webhook_secret,
    )

    return CrawlResponse(
        job_id=job_id,
        status="processing",
        poll_url=f"/v1/jobs/{job_id}",
    )


@router.post(
    "/pipeline",
    response_model=Union[PipelineResponse, CrawlResponse],
    summary="Search + Extract in one call",
    description="Search the web, then extract structured data from the top results. "
    "Costs 1 credit for search + 1 credit per extraction. "
    "If webhook_url is provided and extract_from > 3, runs asynchronously.",
    responses={
        200: {"description": "Pipeline results (sync) or job created (async)"},
        402: {"description": "Insufficient credits"},
        503: {"description": "Browser pool not ready"},
    },
)
async def pipeline_endpoint(
    req: PipelineRequest,
    response: Response,
    user_info: dict = Depends(get_api_key_user),
) -> Union[PipelineResponse, CrawlResponse]:
    pool = get_browser_pool()
    if pool is None:
        raise HTTPException(503, "Browser pool not initialized")

    # Async mode: webhook_url provided and extract_from > 3
    if req.webhook_url and req.extract_from > 3:
        return await _pipeline_async(req, user_info)

    # Total credits: 1 (search) + extract_from (extractions)
    total_credits = 1 + req.extract_from

    rl_headers = await check_rate_limit(user_info)
    credit_headers = await reserve_credits(user_info, credits=total_credits)

    start = time.monotonic()
    completed = False
    actual_extract_credits = 0

    try:
        # Step 1: Execute search
        search_results = await execute_search(
            query=req.query,
            categories=["general"],
            count=req.max_results,
            language=req.search_params.language,
        )

        results_list = search_results.get("results", [])
        urls_to_extract = results_list[: req.extract_from]

        if not urls_to_extract:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            completed = True
            # Release unused extract credits
            unused = req.extract_from
            if unused > 0:
                await release_credits(user_info, unused)

            for k, v in {**rl_headers, **credit_headers}.items():
                response.headers[k] = v
            return PipelineResponse(
                query=req.query,
                results=[],
                meta=PipelineMeta(
                    search_credits=1,
                    extract_credits=0,
                    total_credits=1,
                    response_time_ms=elapsed_ms,
                ),
            )

        # Step 2: Extract from top URLs in parallel
        timeout_ms = req.timeout * 1000
        sem = asyncio.Semaphore(5)

        async def _extract_with_sem(url: str, title: str) -> PipelineResultItem:
            async with sem:
                return await _extract_single_url(pool, url, title, req.schema_, timeout_ms)

        tasks = [
            _extract_with_sem(r["url"], r.get("title", ""))
            for r in urls_to_extract
        ]
        extraction_results = await asyncio.gather(*tasks)

        # Count successful extractions for credit accounting
        actual_extract_credits = sum(
            1 for r in extraction_results if r.extracted_data is not None
        )

        # Release credits for failed extractions
        failed_count = len(urls_to_extract) - actual_extract_credits
        unused_credits = (req.extract_from - len(urls_to_extract)) + failed_count
        if unused_credits > 0:
            await release_credits(user_info, unused_credits)

        elapsed_ms = int((time.monotonic() - start) * 1000)
        completed = True

        for k, v in {**rl_headers, **credit_headers}.items():
            response.headers[k] = v

        return PipelineResponse(
            query=req.query,
            results=list(extraction_results),
            meta=PipelineMeta(
                search_credits=1,
                extract_credits=actual_extract_credits,
                total_credits=1 + actual_extract_credits,
                response_time_ms=elapsed_ms,
            ),
        )

    except HTTPException:
        raise
    except Exception:
        await release_credits(user_info, total_credits)
        raise
    finally:
        if completed:
            elapsed = int((time.monotonic() - start) * 1000)
            asyncio.create_task(
                record_usage_to_db(
                    user_info["api_key_id"],
                    "/v1/pipeline",
                    1 + actual_extract_credits,
                    False,
                    elapsed,
                )
            )
