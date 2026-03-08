"""Pydantic models for the /v1/browse endpoint — interactive browser actions."""

from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl, model_validator


class BrowseAction(BaseModel):
    type: Literal[
        "navigate", "wait", "click", "fill", "type", "select",
        "scroll", "press", "screenshot", "extract", "evaluate",
    ]
    # navigate
    url: str | None = None
    # wait / click / fill / type / select / screenshot (element) / extract
    selector: str | None = None
    # fill / type / select
    value: str | None = None
    # wait
    timeout: int = Field(10000, ge=100, le=60000)
    # type
    delay: int | None = Field(None, ge=0, le=1000)
    # scroll
    direction: Literal["up", "down"] | None = None
    amount: int = Field(500, ge=0, le=10000)
    # press
    key: str | None = None
    # screenshot
    full_page: bool = False
    # extract
    format: Literal["markdown", "html", "text"] = "text"
    # evaluate
    expression: str | None = None

    @model_validator(mode="after")
    def validate_action_fields(self) -> "BrowseAction":
        t = self.type
        if t == "navigate" and not self.url:
            raise ValueError("'navigate' action requires 'url'")
        if t in ("wait", "click", "fill", "type", "select") and not self.selector:
            raise ValueError(f"'{t}' action requires 'selector'")
        if t in ("fill", "type") and self.value is None:
            raise ValueError(f"'{t}' action requires 'value'")
        if t == "select" and self.value is None:
            raise ValueError("'select' action requires 'value'")
        if t == "scroll" and not self.direction:
            raise ValueError("'scroll' action requires 'direction'")
        if t == "press" and not self.key:
            raise ValueError("'press' action requires 'key'")
        if t == "evaluate" and not self.expression:
            raise ValueError("'evaluate' action requires 'expression'")
        return self


class ViewportConfig(BaseModel):
    width: int = Field(1280, ge=320, le=3840)
    height: int = Field(720, ge=240, le=2160)


class BrowseRequest(BaseModel):
    url: HttpUrl
    actions: list[BrowseAction] = Field(..., min_length=1, max_length=20)
    viewport: ViewportConfig | None = None
    user_agent: str | None = None
    proxy: Literal["none", "datacenter", "residential"] | None = None
    timeout: int = Field(30000, ge=1000, le=60000)


class ActionResult(BaseModel):
    action: str
    success: bool
    data: str | None = None
    content: str | None = None
    error: str | None = None


class BrowseResponse(BaseModel):
    success: bool
    url: str
    results: list[ActionResult]
    final_url: str
    credits_used: int
