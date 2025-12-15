from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, Field


class ResourcePathItem(BaseModel):
    """Resource path item for representing parent hierarchy."""

    id: str
    parent_id: str | None = None
    name: str
    resource_type: Literal["folder", "doc", "file"]
    created_at: str | None = None
    updated_at: str | None = None
    attrs: dict | None = None
    file_id: str | None = None


class ResourceInfo(BaseModel):
    """Resource information model returned by backend API."""

    id: str
    name: str
    resource_type: Literal["folder", "doc", "file"]
    namespace_id: str | None = Field(default=None)
    parent_id: str | None = Field(default=None)
    content: str | None = Field(default=None)
    tags: list[str] | None = Field(default=None)
    attrs: dict | None = Field(default=None)
    global_permission: str | None = Field(default=None)
    path: list[ResourcePathItem] | None = Field(
        default=None, description="List of parent resources (ancestors)"
    )
    created_at: str | None = Field(default=None)
    updated_at: str | None = Field(default=None)
    short_id: str | None = Field(default=None, description="Short ID for LLM reference")


class ResourceToolResult(BaseModel):
    """Resource tool execution result."""

    success: bool = True
    data: list[ResourceInfo] | ResourceInfo | None = None
    error: str | None = None

    def to_tool_content(self) -> str:
        """Convert to tool call response content."""
        return json.dumps(
            self.model_dump(exclude_none=True), ensure_ascii=False, indent=2
        )
