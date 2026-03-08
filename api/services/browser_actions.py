"""Browser action execution engine for /v1/browse endpoint."""

import base64
import logging

from playwright.async_api import Page

from api.models.browse import BrowseAction, ActionResult
from api.services.html_cleaner import clean_html, html_to_text

logger = logging.getLogger(__name__)

DEFAULT_ACTION_TIMEOUT = 10000  # 10s per action


async def execute_actions(page: Page, actions: list[BrowseAction]) -> list[ActionResult]:
    """Execute a sequence of browser actions, returning results for each."""
    results: list[ActionResult] = []

    for action in actions:
        try:
            result = await _execute_single(page, action)
            results.append(result)
        except Exception as e:
            results.append(ActionResult(action=action.type, success=False, error=str(e)))
            # wait failures block subsequent actions
            if action.type == "wait":
                break

    return results


async def _execute_single(page: Page, action: BrowseAction) -> ActionResult:
    """Execute a single browser action and return its result."""
    t = action.type

    if t == "navigate":
        await page.goto(action.url, timeout=action.timeout)
        return ActionResult(action=t, success=True)

    if t == "wait":
        await page.wait_for_selector(action.selector, timeout=action.timeout)
        return ActionResult(action=t, success=True)

    if t == "click":
        await page.click(action.selector, timeout=DEFAULT_ACTION_TIMEOUT)
        return ActionResult(action=t, success=True)

    if t == "fill":
        await page.fill(action.selector, action.value, timeout=DEFAULT_ACTION_TIMEOUT)
        return ActionResult(action=t, success=True)

    if t == "type":
        kwargs = {"timeout": DEFAULT_ACTION_TIMEOUT}
        if action.delay is not None:
            kwargs["delay"] = action.delay
        await page.type(action.selector, action.value, **kwargs)
        return ActionResult(action=t, success=True)

    if t == "select":
        await page.select_option(action.selector, action.value, timeout=DEFAULT_ACTION_TIMEOUT)
        return ActionResult(action=t, success=True)

    if t == "scroll":
        pixels = action.amount if action.direction == "down" else -action.amount
        await page.evaluate(f"window.scrollBy(0, {pixels})")
        return ActionResult(action=t, success=True)

    if t == "press":
        await page.keyboard.press(action.key)
        return ActionResult(action=t, success=True)

    if t == "screenshot":
        if action.selector:
            element = await page.query_selector(action.selector)
            if element is None:
                return ActionResult(action=t, success=False, error=f"Element not found: {action.selector}")
            img_bytes = await element.screenshot()
        else:
            img_bytes = await page.screenshot(full_page=action.full_page)
        img_b64 = base64.b64encode(img_bytes).decode()
        return ActionResult(action=t, success=True, data=img_b64)

    if t == "extract":
        if action.selector:
            element = await page.query_selector(action.selector)
            if element is None:
                return ActionResult(action=t, success=False, error=f"Element not found: {action.selector}")
            raw_html = await element.inner_html()
        else:
            raw_html = await page.content()

        if action.format == "html":
            content = clean_html(raw_html)
        elif action.format == "markdown":
            content = html_to_text(clean_html(raw_html))
        else:  # text
            content = html_to_text(raw_html)
        return ActionResult(action=t, success=True, content=content)

    if t == "evaluate":
        result = await page.evaluate(action.expression)
        return ActionResult(action=t, success=True, data=str(result) if result is not None else None)

    return ActionResult(action=t, success=False, error=f"Unknown action type: {t}")
