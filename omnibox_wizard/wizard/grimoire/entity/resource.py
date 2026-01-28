from __future__ import annotations

import json
from typing import Literal, TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from omnibox_wizard.wizard.grimoire.entity.retrieval import Citation


class ResourcePathItem(BaseModel):
    """Resource path item for representing parent hierarchy."""

    id: str
    parent_id: str | None = None
    name: str
    resource_type: Literal["folder", "doc", "file", "link"]
    created_at: str | None = None
    updated_at: str | None = None
    attrs: dict | None = None
    file_id: str | None = None


class ResourceInfo(BaseModel):
    """Resource information model returned by backend API."""

    id: str
    name: str
    resource_type: Literal["folder", "doc", "file", "link"]
    namespace_id: str | None = Field(default=None)
    parent_id: str | None = Field(default=None)
    content: str | None = Field(default=None)
    tags: list[dict] | None = Field(default=None)
    attrs: dict | None = Field(default=None)
    global_permission: str | None = Field(default=None)
    path: list[ResourcePathItem] | None = Field(
        default=None, description="List of parent resources (ancestors)"
    )
    created_at: str | None = Field(default=None)
    updated_at: str | None = Field(default=None)

    # short_id: str | None = Field(default=None, description="Short ID for LLM reference")

    @property
    def summary(self) -> str:
        """Generate summary from content for metadata-only mode."""
        if self.content and len(self.content) > 200:
            return self.content[:200] + "..."
        return self.content or ""

    def to_citation(self) -> "Citation":
        """Convert ResourceInfo to Citation for reference tracking."""
        from omnibox_wizard.wizard.grimoire.entity.retrieval import Citation

        return Citation(
            title=self.name,
            snippet=self.content,
            link=self.id,
            namespace_id=self.namespace_id,
            updated_at=self.updated_at,
            source="private",
        )


class ResourceToolResult(BaseModel):
    """Resource tool execution result."""

    success: bool = True
    data: list[ResourceInfo] | ResourceInfo | None = None
    error: str | None = None
    hint: str | None = Field(
        default=None,
        description="Hint for LLM on what to do next with the result"
    )
    metadata_only: bool = Field(
        default=False,
        description="If True, exclude full content and only return metadata"
    )
    max_resource_limit: int = Field(default=50)

    def to_citations(self) -> list["Citation"]:
        """Convert all ResourceInfo in data to Citations."""
        if not self.data:
            return []
        if isinstance(self.data, list):
            return [r.to_citation() for r in self.data]
        return [self.data.to_citation()]

    def to_tool_content(self) -> str:
        """Convert to tool call response content."""
        # Exclude attrs field to reduce noise for LLM
        exclude_fields = {"attrs"}

        # If metadata_only mode, also exclude content field
        if self.metadata_only:
            exclude_fields.add("content")

        def process_data(data):
            """Recursively exclude attrs and rename id to resource_id."""
            if isinstance(data, dict):
                result = {}
                for k, v in data.items():
                    if k in exclude_fields:
                        continue
                    # Simplify tags: convert objects to string array
                    if k == "tags" and isinstance(v, list):
                        result[k] = [
                            tag.get("name") if isinstance(tag, dict) else tag
                            for tag in v
                        ]
                        continue

                    # Strip timestamps from path items
                    if k == "path" and isinstance(v, list):
                        result[k] = [
                            {pk: pv for pk, pv in path_item.items()
                             if pk not in ("created_at", "updated_at")}
                            for path_item in v
                        ]
                        result[k] = [process_data(item) for item in result[k]]
                        continue

                    # Simplify timestamp format: ISO 8601 → yyyy-mm-dd
                    if k in ("created_at", "updated_at") and isinstance(v, str):
                        result[k] = v.split("T")[0] if "T" in v else v
                        continue

                    # Rename 'id' → 'resource_id' to make purpose explicit
                    new_key = "resource_id" if k == "id" else k
                    result[new_key] = process_data(v)
                return result
            elif isinstance(data, list):
                return [process_data(item) for item in data[:self.max_resource_limit]]
            return data

        dump = self.model_dump(exclude_none=True)

        if self.data and isinstance(self.data, list) and len(self.data) > self.max_resource_limit:
            dump["hint"] = f"**💡Hint To User:**\nFound {len(self.data)} results. Due to the model's context window limits, only the first {self.max_resource_limit} were processed. Please try a more specific query for better accuracy."
        dump = process_data(dump)
        return json.dumps(dump, ensure_ascii=False, indent=2)
