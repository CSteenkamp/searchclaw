"""Pydantic models for the /v1/agent endpoint — autonomous data gathering."""

from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl


class AgentRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=2000)
    schema_: dict[str, Any] | None = Field(None, alias="schema")
    urls: list[HttpUrl] | None = None
    max_credits: int = Field(10, ge=1, le=50)
    max_sources: int = Field(5, ge=1, le=20)
    webhook_url: HttpUrl | None = None
    webhook_secret: str | None = None

    model_config = {"populate_by_name": True}


class AgentStep(BaseModel):
    phase: Literal["search", "filter", "extract", "merge"]
    queries: list[str] | None = None
    results: int | None = None
    urls_selected: int | None = None
    pages_processed: int | None = None
    pages_succeeded: int | None = None
    output_type: Literal["structured", "markdown"] | None = None


class AgentSource(BaseModel):
    url: str
    title: str | None = None


class AgentResponse(BaseModel):
    success: bool
    status: Literal["completed", "processing", "failed"]
    job_id: str | None = None
    data: dict[str, Any] | str | None = None
    sources: list[AgentSource] = []
    credits_used: int = 0
    steps: list[AgentStep] = []
    error: str | None = None
