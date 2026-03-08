"""Pydantic models for the pipeline endpoint."""

from typing import Any, Optional

from pydantic import BaseModel, Field


class SearchParams(BaseModel):
    engines: list[str] = Field(default_factory=lambda: ["google", "bing"])
    language: str = "en"
    region: Optional[str] = None


class PipelineRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)
    schema_: dict[str, Any] = Field(..., alias="schema")
    max_results: int = Field(10, ge=1, le=50)
    extract_from: int = Field(5, ge=1, le=20)
    search_params: SearchParams = Field(default_factory=SearchParams)
    timeout: int = Field(30, ge=5, le=120)
    webhook_url: Optional[str] = Field(None, description="HTTPS URL to receive results on completion")
    webhook_secret: Optional[str] = Field(None, description="Secret for HMAC-SHA256 signature verification")

    model_config = {"populate_by_name": True}


class PipelineResultItem(BaseModel):
    url: str
    title: str
    extracted_data: Optional[dict[str, Any]] = None
    error: Optional[str] = None


class PipelineMeta(BaseModel):
    search_credits: int = 1
    extract_credits: int = 0
    total_credits: int = 0
    response_time_ms: int = 0
    cached: bool = False


class PipelineResponse(BaseModel):
    query: str
    results: list[PipelineResultItem] = []
    meta: PipelineMeta = PipelineMeta()
