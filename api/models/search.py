"""Search request/response models."""

from pydantic import BaseModel
from typing import Optional


class SearchResult(BaseModel):
    """A single search result."""

    title: str
    url: str
    snippet: str
    source: str = ""
    position: int = 0


class InfoBox(BaseModel):
    """Knowledge panel / infobox."""

    title: str
    content: str = ""
    url: str = ""


class SearchMeta(BaseModel):
    """Response metadata."""

    total_results: int = 0
    cached: bool = False
    response_time_ms: int = 0
    engines_used: list[str] = []


class SearchRequest(BaseModel):
    """Search request parameters."""

    q: str
    count: int = 10
    offset: int = 0
    country: Optional[str] = None
    language: str = "en"
    safesearch: int = 1
    freshness: Optional[str] = None


class SearchSource(BaseModel):
    """A source reference for AI search context."""

    title: str
    url: str
    snippet: str


class SearchResponse(BaseModel):
    """Search response."""

    model_config = {"extra": "allow"}

    query: str
    results: list[SearchResult] = []
    infobox: Optional[InfoBox] = None
    suggestions: list[str] = []
    meta: SearchMeta = SearchMeta()
    context: Optional[str] = None
    sources: Optional[list[SearchSource]] = None
