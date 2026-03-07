"""POST /v1/crawl — async crawl job creation."""

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException

from api.middleware.auth import get_api_key_user
from api.middleware.rate_limit import check_rate_limit, reserve_credits
from api.models.job import CrawlRequest, CrawlResponse
from api.services.cache import get_redis_client

router = APIRouter(tags=["crawl"])


@router.post(
    "/crawl",
    response_model=CrawlResponse,
    summary="Create an async crawl job",
    description="Start a multi-page crawl job that extracts data across paginated results. "
    "Returns a job ID for polling via /v1/jobs/{job_id}.",
    responses={
        200: {"description": "Job created successfully"},
        503: {"description": "Redis not available for job tracking"},
    },
)
async def crawl_endpoint(
    req: CrawlRequest,
    user_info: dict = Depends(get_api_key_user),
) -> CrawlResponse:
    """Create an async crawl job."""
    from api.workers.crawl_worker import crawl_and_extract

    await check_rate_limit(user_info)
    await reserve_credits(user_info, credits=1)

    job_id = f"job_{uuid.uuid4().hex[:12]}"

    # Store initial job status in Redis
    redis_client = get_redis_client()
    if redis_client:
        await redis_client.set(
            f"job:{job_id}:status",
            json.dumps({"status": "queued", "pages_crawled": 0, "items_extracted": 0}),
            ex=3600,
        )

    # Dispatch Celery task
    crawl_and_extract.delay(
        job_id=job_id,
        url=str(req.url),
        schema=req.schema_,
        prompt=req.prompt,
        list_selector=req.list_selector,
        pagination=req.pagination.model_dump() if req.pagination else None,
        max_items=req.max_items,
        timeout_ms=req.timeout_ms,
    )

    return CrawlResponse(
        job_id=job_id,
        status="processing",
        poll_url=f"/v1/jobs/{job_id}",
    )
