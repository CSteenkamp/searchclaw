"""POST /v1/screenshot — capture page screenshot."""

import asyncio
import base64
import hashlib
import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import Response as RawResponse

from api.middleware.auth import get_api_key_user
from api.middleware.rate_limit import check_rate_limit, reserve_credits, release_credits, record_usage_to_db
from api.models.job import ScreenshotRequest, ScreenshotResponse
from api.services.browser_pool import get_browser_pool
from api.services.cache import get_cached, set_cached

router = APIRouter(tags=["screenshot"])


def _make_screenshot_cache_key(url: str, width: int, height: int, fmt: str, full_page: bool) -> str:
    raw = f"screenshot:{url}:{width}x{height}:{fmt}:{full_page}"
    digest = hashlib.sha256(raw.encode()).hexdigest()
    return f"screenshot:{digest}"


@router.post(
    "/screenshot",
    summary="Capture a page screenshot",
    description="Render a webpage and capture a PNG or JPEG screenshot.",
    responses={
        200: {"description": "Screenshot captured"},
        502: {"description": "Failed to capture screenshot"},
        503: {"description": "Browser pool not ready"},
    },
)
async def screenshot_endpoint(
    req: ScreenshotRequest,
    request: Request,
    response: Response,
    user_info: dict = Depends(get_api_key_user),
):
    """Capture a screenshot of a URL."""
    pool = get_browser_pool()
    if pool is None:
        raise HTTPException(503, "Browser pool not initialized")

    rl_headers = await check_rate_limit(user_info)
    credit_headers = await reserve_credits(user_info, credits=1)

    start = time.monotonic()
    url = str(req.url)
    completed = False
    is_cached = False

    try:
        # Check cache
        cache_key = _make_screenshot_cache_key(url, req.width, req.height, req.format, req.full_page)
        cached = await get_cached(cache_key)
        if cached is not None:
            accept = request.headers.get("accept", "")
            if "image/" in accept:
                img_bytes = base64.b64decode(cached["image_base64"])
                media = "image/png" if cached["format"] == "png" else "image/jpeg"
                completed = True
                is_cached = True
                return RawResponse(content=img_bytes, media_type=media)
            cached["meta"]["cached"] = True
            completed = True
            is_cached = True
            for k, v in {**rl_headers, **credit_headers}.items():
                response.headers[k] = v
            return ScreenshotResponse(**cached)

        # Render page and take screenshot
        page = await pool.get_page()
        try:
            await page.set_viewport_size({"width": req.width, "height": req.height})
            await page.goto(url, wait_until="networkidle", timeout=30000)

            screenshot_opts = {"full_page": req.full_page, "type": req.format}
            if req.format == "jpeg":
                screenshot_opts["quality"] = req.quality

            img_bytes = await page.screenshot(**screenshot_opts)
        except Exception as e:
            await pool.release_page(page)
            raise HTTPException(502, f"Failed to capture screenshot: {e}")
        finally:
            await pool.release_page(page)

        img_b64 = base64.b64encode(img_bytes).decode()

        # Cache
        cache_data = {
            "url": url, "format": req.format, "image_base64": img_b64,
            "meta": {"cached": False, "credits_used": 1},
        }
        await set_cached(cache_key, cache_data)

        completed = True
        for k, v in {**rl_headers, **credit_headers}.items():
            response.headers[k] = v

        # Content negotiation
        accept = request.headers.get("accept", "")
        if "image/" in accept:
            media = "image/png" if req.format == "png" else "image/jpeg"
            return RawResponse(content=img_bytes, media_type=media)

        return ScreenshotResponse(
            url=url, format=req.format, image_base64=img_b64,
            meta={"cached": False, "credits_used": 1},
        )

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
                    user_info["api_key_id"], "/v1/screenshot", 1, is_cached, elapsed
                )
            )
