"""Pydantic models for the /v1/map endpoint."""

from typing import Literal, Optional

from pydantic import BaseModel, Field, HttpUrl


class MapRequest(BaseModel):
    url: HttpUrl
    max_pages: int = Field(100, ge=1, le=500)
    include_subdomains: bool = False
    search: Optional[str] = None
    ignore_sitemap: bool = False
    limit: int = Field(50, ge=1, le=500)

    model_config = {"populate_by_name": True}


class MapURL(BaseModel):
    url: str
    title: Optional[str] = None
    source: Literal["crawl", "sitemap"] = "crawl"


class MapResponse(BaseModel):
    success: bool = True
    url: str
    total_discovered: int = 0
    urls: list[MapURL] = []
    credits_used: int = 1
