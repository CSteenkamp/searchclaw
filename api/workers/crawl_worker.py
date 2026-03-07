"""Celery task for async crawl jobs."""

import json
import logging
import time

import redis

from api.config import get_settings
from api.workers import celery_app

logger = logging.getLogger(__name__)

_redis_client = None


def _get_redis():
    global _redis_client
    if _redis_client is None:
        settings = get_settings()
        _redis_client = redis.from_url(settings.redis_url)
    return _redis_client


def _update_job_status(job_id: str, status: str, **extra):
    """Update job status in Redis."""
    r = _get_redis()
    data = {"status": status, **extra}
    r.set(f"job:{job_id}:status", json.dumps(data), ex=3600)


def _append_results(job_id: str, items: list):
    """Append extracted items to job results in Redis."""
    r = _get_redis()
    key = f"job:{job_id}:results"
    for item in items:
        r.rpush(key, json.dumps(item))
    r.expire(key, 3600)


def _get_results(job_id: str) -> list:
    """Get all results for a job from Redis."""
    r = _get_redis()
    raw = r.lrange(f"job:{job_id}:results", 0, -1)
    return [json.loads(item) for item in raw]


@celery_app.task(name="crawl_and_extract", bind=True)
def crawl_and_extract(
    self,
    job_id: str,
    url: str,
    schema: dict | None = None,
    prompt: str | None = None,
    list_selector: str | None = None,
    pagination: dict | None = None,
    max_items: int = 100,
    timeout_ms: int = 60000,
):
    """Crawl pages and extract data asynchronously."""
    import asyncio

    start_time = time.monotonic()
    max_pages = pagination.get("max_pages", 10) if pagination else 1

    _update_job_status(
        job_id, "processing",
        pages_crawled=0, total_pages=max_pages, items_extracted=0,
    )

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(
                _crawl_pages(
                    job_id=job_id, url=url, schema=schema, prompt=prompt,
                    list_selector=list_selector, pagination=pagination,
                    max_items=max_items, max_pages=max_pages, timeout_ms=timeout_ms,
                )
            )
        finally:
            loop.close()

        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        all_results = _get_results(job_id)
        status = "completed" if result["pages_succeeded"] == result["pages_crawled"] else "partial"

        _update_job_status(
            job_id, status,
            pages_crawled=result["pages_crawled"], total_pages=max_pages,
            items_extracted=len(all_results), duration_ms=elapsed_ms,
            credits_used=result["pages_crawled"],
        )
        return {"status": status, "items": len(all_results)}

    except Exception as e:
        logger.exception("Crawl job %s failed", job_id)
        _update_job_status(job_id, "failed", error=str(e))
        raise


async def _crawl_pages(
    job_id: str, url: str, schema: dict | None, prompt: str | None,
    list_selector: str | None, pagination: dict | None,
    max_items: int, max_pages: int, timeout_ms: int,
) -> dict:
    """Crawl pages using async Playwright."""
    from playwright.async_api import async_playwright

    from api.services.extractor import extract

    pages_crawled = 0
    pages_succeeded = 0
    total_items = 0
    current_url = url

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context()

        try:
            for page_num in range(max_pages):
                if total_items >= max_items:
                    break

                page = await context.new_page()
                try:
                    await page.goto(current_url, wait_until="networkidle", timeout=timeout_ms)
                    html = await page.content()
                    pages_crawled += 1

                    items = await _extract_from_page(
                        html, current_url, schema, prompt, list_selector
                    )

                    remaining = max_items - total_items
                    items = items[:remaining]

                    if items:
                        _append_results(job_id, items)
                        total_items += len(items)

                    pages_succeeded += 1

                    _update_job_status(
                        job_id, "processing",
                        pages_crawled=pages_crawled, total_pages=max_pages,
                        items_extracted=total_items,
                    )

                    next_url = await _get_next_url(page, current_url, pagination, page_num)
                    if next_url is None:
                        break
                    current_url = next_url

                except Exception as e:
                    logger.warning("Failed to crawl page %s: %s", current_url, e)
                    pages_crawled += 1
                finally:
                    await page.close()

        finally:
            await browser.close()

    return {"pages_crawled": pages_crawled, "pages_succeeded": pages_succeeded}


async def _extract_from_page(
    html: str, url: str, schema: dict | None, prompt: str | None,
    list_selector: str | None,
) -> list[dict]:
    """Extract items from a single page."""
    from bs4 import BeautifulSoup

    from api.services.extractor import extract

    if list_selector:
        soup = BeautifulSoup(html, "lxml")
        elements = soup.select(list_selector)
        items = []
        for el in elements:
            el_html = str(el)
            try:
                result = await extract(el_html, url, schema=schema, prompt=prompt)
                items.append(result.data)
            except Exception:
                logger.warning("Failed to extract element")
        return items
    else:
        try:
            result = await extract(html, url, schema=schema, prompt=prompt)
            return [result.data]
        except Exception:
            logger.warning("Failed to extract page")
            return []


async def _get_next_url(page, current_url: str, pagination: dict | None, page_num: int) -> str | None:
    """Determine the next URL based on pagination config."""
    if not pagination:
        return None

    pag_type = pagination.get("type", "next_button")

    if pag_type == "next_button":
        selector = pagination.get("selector")
        if not selector:
            return None
        try:
            next_btn = await page.query_selector(selector)
            if next_btn and await next_btn.is_visible():
                await next_btn.click()
                await page.wait_for_load_state("networkidle", timeout=15000)
                return page.url
        except Exception:
            pass
        return None

    elif pag_type == "url_pattern":
        pattern = pagination.get("pattern")
        if not pattern:
            return None
        return pattern.replace("{page}", str(page_num + 2))

    elif pag_type == "infinite_scroll":
        try:
            prev_height = await page.evaluate("document.body.scrollHeight")
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(2000)
            new_height = await page.evaluate("document.body.scrollHeight")
            if new_height > prev_height:
                return current_url
        except Exception:
            pass
        return None

    return None
