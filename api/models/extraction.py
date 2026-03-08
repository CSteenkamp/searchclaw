"""Pydantic models for extraction endpoints."""

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, HttpUrl, model_validator


class ChunkingConfig(BaseModel):
    """Configuration for content chunking."""
    enabled: bool = False
    max_chunk_size: int = Field(500, ge=50, le=10000)
    overlap: int = Field(50, ge=0, le=500)
    strategy: Literal["fixed", "sentence", "semantic"] = "fixed"


class Chunk(BaseModel):
    """A single content chunk."""
    index: int
    text: str
    char_count: int
    metadata: dict[str, Any] = {}


class ExtractRequest(BaseModel):
    url: HttpUrl
    schema_: dict[str, Any] | None = Field(None, alias="schema")
    prompt: str | None = None
    wait_for: Literal["networkidle", "domcontentloaded", "load"] = "networkidle"
    timeout_ms: int = Field(30000, ge=1000, le=60000)
    cache: bool = True
    proxy: Literal["none", "datacenter", "residential"] | None = None
    chunking: Optional[ChunkingConfig] = None

    model_config = {"populate_by_name": True}

    @model_validator(mode="after")
    def require_schema_or_prompt(self) -> "ExtractRequest":
        if self.schema_ is None and self.prompt is None:
            raise ValueError("Must provide either 'schema' or 'prompt' (or both)")
        return self


class ExtractionMeta(BaseModel):
    cached: bool = False
    response_time_ms: int
    credits_used: int = 1
    extraction_method: Literal["rule", "llm", "raw"]
    model_used: str | None = None
    tokens_used: int | None = None
    page_title: str | None = None


class ExtractResponse(BaseModel):
    url: str
    data: dict[str, Any] | str
    meta: ExtractionMeta
    chunks: Optional[list[Chunk]] = None
    total_chunks: Optional[int] = None
