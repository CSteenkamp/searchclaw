"""POST /v1/markdown — convert URL to clean markdown."""

import asyncio
import hashlib
import time

import html2text
from fastapi import APIRouter, Depends, HTTPException, Response

from api.middleware.auth import get_api_key_user
from api.middleware.rate_limit import check_rate_limit, reserve_credits, release_credits, record_usage_to_db
from api.models.job import MarkdownRequest, MarkdownResponse
from api.services.browser_pool import get_browser_pool
from api.services.cache import get_cached, set_cached
from api.services.html_cleaner import clean_html

router = APIRouter(tags=["Extract"])


def _make_markdown_cache_key(url: str) -> str:
    digest = hashlib.sha256(f"markdown:{url}".encode()).hexdigest()
    return f"markdown:{digest}"


def _html_to_markdown(
    html: str,
    include_images: bool = True,
    include_links: bool = True,
    main_content_only: bool = True,
) -> str:
    """Convert HTML to clean markdown."""
    if main_content_only:
        html = clean_html(html)

    converter = html2text.HTML2Text()
    converter.ignore_images = not include_images
    converter.ignore_links = not include_links
    converter.ignore_emphasis = False
    converter.body_width = 0
    converter.protect_links = True
    converter.unicode_snob = True

    return converter.handle(html).strip()


@router.post(
    "/markdown",
    response_model=MarkdownResponse,
    summary="Convert a URL to markdown",
    description="Render a webpage and convert it to clean markdown. "
    "Useful for RAG pipelines, LLM context, and content archival.",
    responses={
        200: {"description": "Markdown conversion successful"},
        502: {"description": "Failed to render target page"},
        503: {"description": "Browser pool not ready"},
    },
)
async def markdown_endpoint(
    req: MarkdownRequest,
    response: Response,
    user_info: dict = Depends(get_api_key_user),
) -> MarkdownResponse:
    """Convert a URL to clean markdown."""
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
        cache_key = _make_markdown_cache_key(url)
        cached = await get_cached(cache_key)
        if cached is not None:
            cached["meta"]["cached"] = True
            is_cached = True
            completed = True
            for k, v in {**rl_headers, **credit_headers}.items():
                response.headers[k] = v
            return MarkdownResponse(**cached)

        # Render page
        try:
            raw_html, page_title = await pool.render_url(url)
        except Exception as e:
            raise HTTPException(502, f"Failed to render page: {e}")

        # Convert to markdown
        markdown = _html_to_markdown(
            raw_html,
            include_images=req.include_images,
            include_links=req.include_links,
            main_content_only=req.main_content_only,
        )

        word_count = len(markdown.split())

        resp = MarkdownResponse(
            url=url,
            title=page_title,
            markdown=markdown,
            meta={"word_count": word_count, "cached": False, "credits_used": 1},
        )

        await set_cached(cache_key, resp.model_dump())

        completed = True
        for k, v in {**rl_headers, **credit_headers}.items():
            response.headers[k] = v
        return resp

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
                    user_info["api_key_id"], "/v1/markdown", 1, is_cached, elapsed
                )
            )
