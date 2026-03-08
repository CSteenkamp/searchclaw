"""POST /v1/browse — interactive browser actions."""

import asyncio
import logging
import time

from fastapi import APIRouter, Depends, HTTPException, Response

from api.middleware.auth import get_api_key_user
from api.middleware.rate_limit import check_rate_limit, reserve_credits, release_credits, record_usage_to_db
from api.models.browse import BrowseRequest, BrowseResponse
from api.services.browser_pool import get_browser_pool
from api.services.browser_actions import execute_actions
from api.services.proxy_manager import get_proxy_manager, resolve_proxy_tier

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Browse"])


@router.post(
    "/browse",
    response_model=BrowseResponse,
    summary="Execute interactive browser actions",
    description="Drive a headless browser session: navigate, click, type, scroll, wait, and extract. "
    "Essential for auth-gated pages, SPAs, and interactive content.",
    responses={
        200: {"description": "Actions executed successfully"},
        402: {"description": "Insufficient credits"},
        422: {"description": "Invalid action list"},
        503: {"description": "Browser pool not ready"},
    },
)
async def browse_endpoint(
    req: BrowseRequest,
    response: Response,
    user_info: dict = Depends(get_api_key_user),
) -> BrowseResponse:
    pool = get_browser_pool()
    if pool is None:
        raise HTTPException(503, "Browser pool not initialized")

    # Resolve proxy tier
    tier = resolve_proxy_tier(req.proxy, user_info["plan"])
    proxy_url = None
    pm = get_proxy_manager()
    if pm and tier != "none":
        proxy_cfg = pm.get_proxy(tier)
        proxy_url = proxy_cfg.url if proxy_cfg else None

    # Credit cost: 1 base + 1 if residential proxy
    credits = 2 if tier == "residential" else 1

    rl_headers = await check_rate_limit(user_info)
    credit_headers = await reserve_credits(user_info, credits=credits)

    start = time.monotonic()
    completed = False
    url = str(req.url)

    try:
        if proxy_url:
            import random
            ctx = await pool._create_context(random.randint(0, 100), proxy_url=proxy_url)
            page = await ctx.new_page()
        else:
            page = await pool.get_page()
        try:
            # Configure viewport if specified
            if req.viewport:
                await page.set_viewport_size({
                    "width": req.viewport.width,
                    "height": req.viewport.height,
                })

            # Set custom user agent if provided
            # (viewport/UA set at context level in pool, but we can override per-page)

            # Navigate to initial URL
            await page.goto(url, timeout=req.timeout)

            # Execute action sequence
            results = await execute_actions(page, req.actions)

            final_url = page.url
        finally:
            if proxy_url:
                await page.close()
                await page.context.close()
            else:
                await pool.release_page(page)

        all_success = all(r.success for r in results)
        completed = True

        for k, v in {**rl_headers, **credit_headers}.items():
            response.headers[k] = v

        return BrowseResponse(
            success=all_success,
            url=url,
            results=results,
            final_url=final_url,
            credits_used=credits,
        )

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
                    user_info["api_key_id"], "/v1/browse", credits, False, elapsed
                )
            )
