"""Browser pool — manages Playwright browser contexts for concurrent page rendering."""

import asyncio
import logging
import random

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from api.config import get_settings

logger = logging.getLogger(__name__)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.2 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
]

VIEWPORTS = [
    {"width": 1920, "height": 1080},
    {"width": 1366, "height": 768},
    {"width": 1536, "height": 864},
    {"width": 1440, "height": 900},
    {"width": 1280, "height": 720},
]

BLOCKED_RESOURCE_TYPES = {"image", "font", "media", "stylesheet"}

# Module-level singleton
_pool: "BrowserPool | None" = None


class BrowserPool:
    """Manages a pool of Playwright browser contexts for concurrent page rendering."""

    def __init__(self, pool_size: int = 3):
        self._pool_size = pool_size
        self._playwright = None
        self._browser: Browser | None = None
        self._available: asyncio.Queue[BrowserContext] = asyncio.Queue()
        self._all_contexts: list[BrowserContext] = []

    async def start(self) -> None:
        """Launch browser and create context pool."""
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=True)
        for i in range(self._pool_size):
            ctx = await self._create_context(i)
            self._all_contexts.append(ctx)
            await self._available.put(ctx)
        logger.info("Browser pool started with %d contexts", self._pool_size)

    async def _create_context(self, index: int) -> BrowserContext:
        ua = USER_AGENTS[index % len(USER_AGENTS)]
        vp = VIEWPORTS[index % len(VIEWPORTS)]
        ctx = await self._browser.new_context(
            user_agent=ua,
            viewport=vp,
            locale=random.choice(["en-US", "en-GB", "en-AU"]),
            timezone_id=random.choice(["America/New_York", "Europe/London", "America/Los_Angeles"]),
        )
        await ctx.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        """)
        await ctx.route("**/*", self._route_handler)
        return ctx

    @staticmethod
    async def _route_handler(route):
        if route.request.resource_type in BLOCKED_RESOURCE_TYPES:
            await route.abort()
        else:
            await route.continue_()

    async def get_page(self) -> Page:
        """Acquire a page from the pool. Caller must call release_page when done."""
        ctx = await self._available.get()
        page = await ctx.new_page()
        return page

    async def release_page(self, page: Page) -> None:
        """Close the page and return its context to the pool."""
        ctx = page.context
        await page.close()
        await self._available.put(ctx)

    async def render_url(
        self,
        url: str,
        wait_for: str = "networkidle",
        timeout_ms: int = 30000,
    ) -> tuple[str, str | None]:
        """Render a URL and return (html_content, page_title)."""
        page = await self.get_page()
        try:
            await page.goto(url, wait_until=wait_for, timeout=timeout_ms)
            html = await page.content()
            title = await page.title()
            return html, title
        finally:
            await self.release_page(page)

    @property
    def status(self) -> dict:
        """Return pool status info."""
        return {
            "pool_size": self._pool_size,
            "available": self._available.qsize(),
            "active": self._pool_size - self._available.qsize(),
            "ready": self._browser is not None,
        }

    async def stop(self) -> None:
        """Close all contexts and the browser."""
        for ctx in self._all_contexts:
            await ctx.close()
        self._all_contexts.clear()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        logger.info("Browser pool stopped")


async def init_browser_pool() -> BrowserPool:
    """Initialize and start the global browser pool."""
    global _pool
    settings = get_settings()
    _pool = BrowserPool(pool_size=settings.browser_pool_size)
    await _pool.start()
    return _pool


async def close_browser_pool() -> None:
    """Shut down the global browser pool."""
    global _pool
    if _pool:
        await _pool.stop()
        _pool = None


def get_browser_pool() -> BrowserPool | None:
    """Get the global browser pool instance."""
    return _pool
