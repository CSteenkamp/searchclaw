"""POST /v1/map — URL discovery via sitemap + BFS crawl."""

import asyncio
import time

from fastapi import APIRouter, Depends, Response

from api.middleware.auth import get_api_key_user
from api.middleware.rate_limit import check_rate_limit, reserve_credits, release_credits, record_usage_to_db
from api.models.map import MapRequest, MapResponse
from api.services.map_service import discover_urls

router = APIRouter(tags=["map"])


@router.post(
    "/map",
    response_model=MapResponse,
    summary="Discover URLs on a domain",
    description="Discover all URLs on a domain via sitemap.xml parsing and BFS crawl. "
    "Returns a deduplicated list of discovered URLs with metadata.",
    responses={
        200: {"description": "URL discovery results"},
        402: {"description": "Insufficient credits"},
    },
)
async def map_endpoint(
    req: MapRequest,
    response: Response,
    user_info: dict = Depends(get_api_key_user),
) -> MapResponse:
    rl_headers = await check_rate_limit(user_info)
    credit_headers = await reserve_credits(user_info, credits=1)

    start = time.monotonic()
    completed = False

    try:
        result = await discover_urls(
            url=str(req.url),
            max_pages=req.max_pages,
            include_subdomains=req.include_subdomains,
            search=req.search,
            ignore_sitemap=req.ignore_sitemap,
            limit=req.limit,
        )

        completed = True
        for k, v in {**rl_headers, **credit_headers}.items():
            response.headers[k] = v
        return MapResponse(**result)

    except Exception:
        await release_credits(user_info, 1)
        raise
    finally:
        if completed:
            elapsed = int((time.monotonic() - start) * 1000)
            asyncio.create_task(
                record_usage_to_db(
                    user_info["api_key_id"], "/v1/map", 1, False, elapsed
                )
            )
