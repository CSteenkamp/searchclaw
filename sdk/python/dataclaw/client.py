"""SearchClaw API client implementation."""

from __future__ import annotations

from typing import Any, Optional

import httpx


class SearchClawError(Exception):
    """Base exception for SearchClaw API errors."""

    def __init__(self, message: str, status_code: Optional[int] = None, response: Optional[dict[str, Any]] = None):
        super().__init__(message)
        self.status_code = status_code
        self.response = response


class AuthError(SearchClawError):
    """Raised when authentication fails (401/403)."""


class RateLimitError(SearchClawError):
    """Raised when rate limit is exceeded (429)."""

    def __init__(self, message: str, retry_after: Optional[int] = None, **kwargs: Any):
        super().__init__(message, **kwargs)
        self.retry_after = retry_after


_DEFAULT_BASE_URL = "https://api.searchclaw.dev/v1"
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
    raise SearchClawError(message, status_code=response.status_code, response=body)


class SearchClaw:
    """Synchronous SearchClaw API client."""

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
        engines: Optional[str] = None,
        format: Optional[str] = None,
    ) -> dict[str, Any]:
        """Perform a web search."""
        params = self._build_params(q=q, count=count, offset=offset, country=country,
                                     language=language, safesearch=safesearch, freshness=freshness,
                                     engines=engines, format=format)
        return self._request("GET", "/search", params=params)

    def news(
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
        """Search for news articles."""
        params = self._build_params(q=q, count=count, offset=offset, country=country,
                                     language=language, safesearch=safesearch, freshness=freshness)
        return self._request("GET", "/news", params=params)

    def images(
        self,
        q: str,
        *,
        count: Optional[int] = None,
        offset: Optional[int] = None,
        country: Optional[str] = None,
        language: Optional[str] = None,
        safesearch: Optional[int] = None,
    ) -> dict[str, Any]:
        """Search for images."""
        params = self._build_params(q=q, count=count, offset=offset, country=country,
                                     language=language, safesearch=safesearch)
        return self._request("GET", "/images", params=params)

    def suggest(self, q: str) -> list[str]:
        """Get search suggestions/autocomplete."""
        return self._request("GET", "/suggest", params={"q": q})

    def ai_search(
        self,
        q: str,
        *,
        count: Optional[int] = None,
        country: Optional[str] = None,
        language: Optional[str] = None,
        freshness: Optional[str] = None,
    ) -> dict[str, Any]:
        """LLM-optimized search (costs 2 credits)."""
        params = self._build_params(q=q, count=count, country=country,
                                     language=language, freshness=freshness)
        return self._request("GET", "/search/ai", params=params)

    def usage(self) -> dict[str, Any]:
        """Get current billing period usage and account info."""
        return self._request("GET", "/usage")

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._client.close()

    def __enter__(self) -> SearchClaw:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    @staticmethod
    def _build_params(**kwargs: Any) -> dict[str, Any]:
        return {k: v for k, v in kwargs.items() if v is not None}


class AsyncSearchClaw:
    """Asynchronous SearchClaw API client."""

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

    async def search(
        self,
        q: str,
        *,
        count: Optional[int] = None,
        offset: Optional[int] = None,
        country: Optional[str] = None,
        language: Optional[str] = None,
        safesearch: Optional[int] = None,
        freshness: Optional[str] = None,
        engines: Optional[str] = None,
        format: Optional[str] = None,
    ) -> dict[str, Any]:
        """Perform a web search."""
        params = self._build_params(q=q, count=count, offset=offset, country=country,
                                     language=language, safesearch=safesearch, freshness=freshness,
                                     engines=engines, format=format)
        return await self._request("GET", "/search", params=params)

    async def news(
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
        """Search for news articles."""
        params = self._build_params(q=q, count=count, offset=offset, country=country,
                                     language=language, safesearch=safesearch, freshness=freshness)
        return await self._request("GET", "/news", params=params)

    async def images(
        self,
        q: str,
        *,
        count: Optional[int] = None,
        offset: Optional[int] = None,
        country: Optional[str] = None,
        language: Optional[str] = None,
        safesearch: Optional[int] = None,
    ) -> dict[str, Any]:
        """Search for images."""
        params = self._build_params(q=q, count=count, offset=offset, country=country,
                                     language=language, safesearch=safesearch)
        return await self._request("GET", "/images", params=params)

    async def suggest(self, q: str) -> list[str]:
        """Get search suggestions/autocomplete."""
        return await self._request("GET", "/suggest", params={"q": q})

    async def ai_search(
        self,
        q: str,
        *,
        count: Optional[int] = None,
        country: Optional[str] = None,
        language: Optional[str] = None,
        freshness: Optional[str] = None,
    ) -> dict[str, Any]:
        """LLM-optimized search (costs 2 credits)."""
        params = self._build_params(q=q, count=count, country=country,
                                     language=language, freshness=freshness)
        return await self._request("GET", "/search/ai", params=params)

    async def usage(self) -> dict[str, Any]:
        """Get current billing period usage and account info."""
        return await self._request("GET", "/usage")

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    async def __aenter__(self) -> AsyncSearchClaw:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()

    @staticmethod
    def _build_params(**kwargs: Any) -> dict[str, Any]:
        return {k: v for k, v in kwargs.items() if v is not None}
