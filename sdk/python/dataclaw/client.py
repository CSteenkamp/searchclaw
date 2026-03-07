"""DataClaw API client — Search, Extract, Crawl, Pipeline."""

from __future__ import annotations

from typing import Any, Optional

import httpx


class DataClawError(Exception):
    """Base exception for DataClaw API errors."""

    def __init__(self, message: str, status_code: Optional[int] = None, response: Optional[dict[str, Any]] = None):
        super().__init__(message)
        self.status_code = status_code
        self.response = response


class AuthError(DataClawError):
    """Raised when authentication fails (401/403)."""


class RateLimitError(DataClawError):
    """Raised when rate limit is exceeded (429)."""

    def __init__(self, message: str, retry_after: Optional[int] = None, **kwargs: Any):
        super().__init__(message, **kwargs)
        self.retry_after = retry_after


_DEFAULT_BASE_URL = "https://api.dataclaw.dev/v1"
_DEFAULT_TIMEOUT = 30.0


def _handle_error(response: httpx.Response) -> None:
    """Raise appropriate exception for error responses."""
    try:
        body = response.json()
    except Exception:
        body = {"detail": response.text}

    message = body.get("detail", f"HTTP {response.status_code}")

    if response.status_code in (401, 403):
        raise AuthError(message, status_code=response.status_code, response=body)
    if response.status_code == 429:
        retry_after = response.headers.get("Retry-After")
        raise RateLimitError(
            message,
            status_code=429,
            response=body,
            retry_after=int(retry_after) if retry_after else None,
        )
    raise DataClawError(message, status_code=response.status_code, response=body)


class DataClaw:
    """Synchronous DataClaw API client."""

    def __init__(
        self,
        api_key: str,
        base_url: str = _DEFAULT_BASE_URL,
        timeout: float = _DEFAULT_TIMEOUT,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(
            base_url=self.base_url,
            headers={"X-API-Key": api_key},
            timeout=timeout,
        )

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        response = self._client.request(method, path, **kwargs)
        if response.status_code >= 400:
            _handle_error(response)
        return response.json()

    # --- Search ---

    def search(
        self,
        q: str,
        *,
        count: Optional[int] = None,
        offset: Optional[int] = None,
        country: Optional[str] = None,
        language: Optional[str] = None,
        safesearch: Optional[int] = None,
        freshness: Optional[str] = None,
    ) -> dict[str, Any]:
        """Perform a web search."""
        params = self._build_params(q=q, count=count, offset=offset, country=country,
                                     language=language, safesearch=safesearch, freshness=freshness)
        return self._request("GET", "/search", params=params)

    def news(self, q: str, **kwargs: Any) -> dict[str, Any]:
        """Search for news articles."""
        params = self._build_params(q=q, **kwargs)
        return self._request("GET", "/news", params=params)

    def images(self, q: str, **kwargs: Any) -> dict[str, Any]:
        """Search for images."""
        params = self._build_params(q=q, **kwargs)
        return self._request("GET", "/images", params=params)

    def suggest(self, q: str) -> dict[str, Any]:
        """Get search suggestions."""
        return self._request("GET", "/suggest", params={"q": q})

    def ai_search(self, q: str, **kwargs: Any) -> dict[str, Any]:
        """LLM-optimized search (costs 2 credits)."""
        params = self._build_params(q=q, **kwargs)
        return self._request("GET", "/search/ai", params=params)

    # --- Extract ---

    def extract(
        self,
        url: str,
        *,
        schema: Optional[dict[str, Any]] = None,
        prompt: Optional[str] = None,
        wait_for: str = "networkidle",
        timeout_ms: int = 30000,
    ) -> dict[str, Any]:
        """Extract structured data from a URL."""
        body: dict[str, Any] = {"url": url}
        if schema:
            body["schema"] = schema
        if prompt:
            body["prompt"] = prompt
        body["wait_for"] = wait_for
        body["timeout_ms"] = timeout_ms
        return self._request("POST", "/extract", json=body)

    def markdown(self, url: str, **kwargs: Any) -> dict[str, Any]:
        """Convert a URL to clean markdown."""
        return self._request("POST", "/markdown", json={"url": url, **kwargs})

    def screenshot(self, url: str, **kwargs: Any) -> dict[str, Any]:
        """Take a screenshot of a URL."""
        return self._request("POST", "/screenshot", json={"url": url, **kwargs})

    # --- Crawl ---

    def crawl(
        self,
        url: str,
        *,
        schema: Optional[dict[str, Any]] = None,
        max_pages: int = 10,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Start an async crawl job."""
        body: dict[str, Any] = {"url": url, "max_pages": max_pages, **kwargs}
        if schema:
            body["schema"] = schema
        return self._request("POST", "/crawl", json=body)

    def get_job(self, job_id: str) -> dict[str, Any]:
        """Get the status of an async job."""
        return self._request("GET", f"/jobs/{job_id}")

    def wait_for_job(self, job_id: str, poll_interval: float = 2.0, timeout: float = 300.0) -> dict[str, Any]:
        """Poll a job until completion."""
        import time
        start = time.monotonic()
        while time.monotonic() - start < timeout:
            result = self.get_job(job_id)
            if result.get("status") in ("completed", "failed"):
                return result
            time.sleep(poll_interval)
        raise DataClawError("Job timed out", status_code=None)

    # --- Pipeline ---

    def pipeline(
        self,
        query: str,
        *,
        schema: dict[str, Any],
        max_results: int = 10,
        extract_from: int = 5,
        search_params: Optional[dict[str, Any]] = None,
        timeout: int = 30,
    ) -> dict[str, Any]:
        """Search + extract in one call."""
        body: dict[str, Any] = {
            "query": query,
            "schema": schema,
            "max_results": max_results,
            "extract_from": extract_from,
            "timeout": timeout,
        }
        if search_params:
            body["search_params"] = search_params
        return self._request("POST", "/pipeline", json=body)

    # --- Account ---

    def usage(self) -> dict[str, Any]:
        """Get current usage and plan info."""
        return self._request("GET", "/usage")

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> DataClaw:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    @staticmethod
    def _build_params(**kwargs: Any) -> dict[str, Any]:
        return {k: v for k, v in kwargs.items() if v is not None}


class AsyncDataClaw:
    """Asynchronous DataClaw API client."""

    def __init__(
        self,
        api_key: str,
        base_url: str = _DEFAULT_BASE_URL,
        timeout: float = _DEFAULT_TIMEOUT,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={"X-API-Key": api_key},
            timeout=timeout,
        )

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        response = await self._client.request(method, path, **kwargs)
        if response.status_code >= 400:
            _handle_error(response)
        return response.json()

    # --- Search ---

    async def search(self, q: str, **kwargs: Any) -> dict[str, Any]:
        """Perform a web search."""
        params = self._build_params(q=q, **kwargs)
        return await self._request("GET", "/search", params=params)

    async def news(self, q: str, **kwargs: Any) -> dict[str, Any]:
        """Search for news articles."""
        params = self._build_params(q=q, **kwargs)
        return await self._request("GET", "/news", params=params)

    async def images(self, q: str, **kwargs: Any) -> dict[str, Any]:
        """Search for images."""
        params = self._build_params(q=q, **kwargs)
        return await self._request("GET", "/images", params=params)

    async def suggest(self, q: str) -> dict[str, Any]:
        """Get search suggestions."""
        return await self._request("GET", "/suggest", params={"q": q})

    async def ai_search(self, q: str, **kwargs: Any) -> dict[str, Any]:
        """LLM-optimized search (costs 2 credits)."""
        params = self._build_params(q=q, **kwargs)
        return await self._request("GET", "/search/ai", params=params)

    # --- Extract ---

    async def extract(
        self,
        url: str,
        *,
        schema: Optional[dict[str, Any]] = None,
        prompt: Optional[str] = None,
        wait_for: str = "networkidle",
        timeout_ms: int = 30000,
    ) -> dict[str, Any]:
        """Extract structured data from a URL."""
        body: dict[str, Any] = {"url": url}
        if schema:
            body["schema"] = schema
        if prompt:
            body["prompt"] = prompt
        body["wait_for"] = wait_for
        body["timeout_ms"] = timeout_ms
        return await self._request("POST", "/extract", json=body)

    async def markdown(self, url: str, **kwargs: Any) -> dict[str, Any]:
        """Convert a URL to clean markdown."""
        return await self._request("POST", "/markdown", json={"url": url, **kwargs})

    async def screenshot(self, url: str, **kwargs: Any) -> dict[str, Any]:
        """Take a screenshot of a URL."""
        return await self._request("POST", "/screenshot", json={"url": url, **kwargs})

    # --- Crawl ---

    async def crawl(
        self,
        url: str,
        *,
        schema: Optional[dict[str, Any]] = None,
        max_pages: int = 10,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Start an async crawl job."""
        body: dict[str, Any] = {"url": url, "max_pages": max_pages, **kwargs}
        if schema:
            body["schema"] = schema
        return await self._request("POST", "/crawl", json=body)

    async def get_job(self, job_id: str) -> dict[str, Any]:
        """Get the status of an async job."""
        return await self._request("GET", f"/jobs/{job_id}")

    async def wait_for_job(self, job_id: str, poll_interval: float = 2.0, timeout: float = 300.0) -> dict[str, Any]:
        """Poll a job until completion."""
        import asyncio
        import time
        start = time.monotonic()
        while time.monotonic() - start < timeout:
            result = await self.get_job(job_id)
            if result.get("status") in ("completed", "failed"):
                return result
            await asyncio.sleep(poll_interval)
        raise DataClawError("Job timed out", status_code=None)

    # --- Pipeline ---

    async def pipeline(
        self,
        query: str,
        *,
        schema: dict[str, Any],
        max_results: int = 10,
        extract_from: int = 5,
        search_params: Optional[dict[str, Any]] = None,
        timeout: int = 30,
    ) -> dict[str, Any]:
        """Search + extract in one call."""
        body: dict[str, Any] = {
            "query": query,
            "schema": schema,
            "max_results": max_results,
            "extract_from": extract_from,
            "timeout": timeout,
        }
        if search_params:
            body["search_params"] = search_params
        return await self._request("POST", "/pipeline", json=body)

    # --- Account ---

    async def usage(self) -> dict[str, Any]:
        """Get current usage and plan info."""
        return await self._request("GET", "/usage")

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> AsyncDataClaw:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()

    @staticmethod
    def _build_params(**kwargs: Any) -> dict[str, Any]:
        return {k: v for k, v in kwargs.items() if v is not None}
