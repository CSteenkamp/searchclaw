"""Pydantic models for crawl jobs, markdown, and screenshot endpoints."""

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, HttpUrl

from api.models.extraction import ChunkingConfig, Chunk

ProxyTier = Literal["none", "datacenter", "residential"]


class PaginationConfig(BaseModel):
    type: Literal["next_button", "url_pattern", "infinite_scroll"] = "next_button"
    selector: str | None = None
    pattern: str | None = None
    max_pages: int = Field(10, ge=1, le=100)


class CrawlRequest(BaseModel):
    url: HttpUrl
    schema_: dict[str, Any] | None = Field(None, alias="schema")
    prompt: str | None = None
    list_selector: str | None = None
    pagination: PaginationConfig | None = None
    max_items: int = Field(100, ge=1, le=1000)
    timeout_ms: int = Field(60000, ge=1000, le=120000)
    proxy: ProxyTier | None = None
    webhook_url: str | None = Field(None, description="HTTPS URL to receive job results on completion")
    webhook_secret: str | None = Field(None, description="Secret for HMAC-SHA256 signature verification")

    model_config = {"populate_by_name": True}


class CrawlResponse(BaseModel):
    job_id: str
    status: str = "processing"
    poll_url: str


class JobProgress(BaseModel):
    pages_crawled: int = 0
    total_pages: int | None = None
    items_extracted: int = 0


class JobStatusResponse(BaseModel):
    job_id: str
    status: Literal["queued", "processing", "completed", "failed", "partial"]
    progress: JobProgress | None = None
    data: list[dict[str, Any]] | None = None
    error: str | None = None
    meta: dict[str, Any] | None = None


class MarkdownRequest(BaseModel):
    url: HttpUrl
    include_images: bool = True
    include_links: bool = True
    main_content_only: bool = True
    proxy: ProxyTier | None = None
    chunking: Optional[ChunkingConfig] = None

    model_config = {"populate_by_name": True}


class MarkdownResponse(BaseModel):
    url: str
    title: str | None = None
    markdown: str
    meta: dict[str, Any]
    chunks: Optional[list[Chunk]] = None
    total_chunks: Optional[int] = None


class ScreenshotRequest(BaseModel):
    url: HttpUrl
    format: Literal["png", "jpeg"] = "png"
    width: int = Field(1280, ge=320, le=3840)
    height: int = Field(720, ge=240, le=2160)
    full_page: bool = False
    quality: int = Field(80, ge=1, le=100)
    proxy: ProxyTier | None = None

    model_config = {"populate_by_name": True}


class ScreenshotResponse(BaseModel):
    url: str
    format: str
    image_base64: str
    meta: dict[str, Any]
