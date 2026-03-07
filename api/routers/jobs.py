"""GET /v1/jobs/{job_id} — job status polling."""

import json

from fastapi import APIRouter, Depends, HTTPException

from api.middleware.auth import get_api_key_user
from api.models.job import JobProgress, JobStatusResponse
from api.services.cache import get_redis_client

router = APIRouter(tags=["jobs"])


@router.get(
    "/jobs/{job_id}",
    response_model=JobStatusResponse,
    summary="Get crawl job status",
    description="Poll for the status and results of an async crawl job created via /v1/crawl.",
    responses={
        200: {"description": "Job status and results"},
        404: {"description": "Job not found or expired"},
        503: {"description": "Redis not available"},
    },
)
async def get_job_status(
    job_id: str,
    user_info: dict = Depends(get_api_key_user),
) -> JobStatusResponse:
    """Get the status and results of an async crawl job."""
    redis_client = get_redis_client()
    if not redis_client:
        raise HTTPException(503, "Redis not available")

    raw_status = await redis_client.get(f"job:{job_id}:status")
    if raw_status is None:
        raise HTTPException(404, f"Job {job_id} not found or expired")

    status_data = json.loads(raw_status)
    status = status_data.get("status", "queued")

    progress = JobProgress(
        pages_crawled=status_data.get("pages_crawled", 0),
        total_pages=status_data.get("total_pages"),
        items_extracted=status_data.get("items_extracted", 0),
    )

    data = None
    if status in ("completed", "partial"):
        raw_results = await redis_client.lrange(f"job:{job_id}:results", 0, -1)
        data = [json.loads(item) for item in raw_results]

    meta = None
    if status in ("completed", "partial"):
        meta = {
            "total_items": progress.items_extracted,
            "pages_crawled": progress.pages_crawled,
            "credits_used": status_data.get("credits_used", progress.pages_crawled),
            "duration_ms": status_data.get("duration_ms", 0),
        }

    error = status_data.get("error") if status == "failed" else None

    return JobStatusResponse(
        job_id=job_id,
        status=status,
        progress=progress,
        data=data,
        error=error,
        meta=meta,
    )
