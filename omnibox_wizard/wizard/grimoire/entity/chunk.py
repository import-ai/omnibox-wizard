import time
from datetime import datetime
from enum import Enum
from typing import Optional, Literal

import shortuuid
from pydantic import Field

from omnibox_wizard.wizard.grimoire.entity.retrieval import BaseRetrieval, Citation, to_prompt, PromptContext
from omnibox_wizard.wizard.grimoire.entity.tools import PrivateSearchResourceType


class ChunkType(str, Enum):
    title: str = "title"  # document title
    doc: str = "doc"  # Whole document
    snippet: str = "snippet"  # Part of section
    keyword: str = "keyword"


def timestamp_to_datetime(timestamp: float, date_format: str = "%Y-%m-%d %H:%M:%S") -> str:
    return datetime.fromtimestamp(timestamp).strftime(date_format)


class Chunk(PromptContext):
    title: str | None = Field(default=None, description="Chunk title, usually the title of the document")
    resource_id: str
    text: str | None = Field(default=None, description="Chunk content")
    chunk_type: ChunkType = Field(description="Chunk type")

    user_id: str
    parent_id: str

    chunk_id: str = Field(description="ID of chunk", default_factory=shortuuid.uuid)
    created_at: float = Field(description="Unix timestamp in float format", default_factory=time.time)
    updated_at: float = Field(description="Unix timestamp in float format", default_factory=time.time)

    start_index: Optional[int] = Field(description="The start char index of this chunk", default=None)
    end_index: Optional[int] = Field(description="The end char index of this chunk, index excluded", default=None)

    @property
    def metadata(self) -> dict:
        return self.model_dump(exclude_none=True, exclude={"chunk_id", "text"})

    def to_prompt(self) -> str:
        lines: list[str] = []
        if self.title:
            lines.append(f"Title: {self.title}")
        if self.text:
            lines.append(f"Snippet:\n{self.text}")
        return "\n".join(lines)


class ResourceChunkRetrieval(BaseRetrieval):
    folder: str | None = Field(default=None, description="The folder of the chunk, if any")
    type: PrivateSearchResourceType | None = Field(default=None, description="The type of the resource")
    chunk: Chunk
    source: Literal["private"] = "private"

    def to_prompt(self, exclude_id: bool = False) -> str:
        citation = self.to_citation()

        tag_attrs: dict = {"source": self.source}
        body_attrs: dict = {}

        if self.chunk.resource_id:
            tag_attrs["resource_id"] = self.chunk.resource_id
        if self.folder:
            tag_attrs["folder"] = self.folder
        if citation.title:
            tag_attrs["title"] = citation.title
        if citation.snippet:
            body_attrs["snippet"] = citation.snippet
        if citation.updated_at:
            tag_attrs["updated_at"] = citation.updated_at
        if self.chunk.start_index is not None:
            tag_attrs["start_index"] = str(self.chunk.start_index)
        if self.chunk.end_index is not None:
            tag_attrs["end_index"] = str(self.chunk.end_index)
        return to_prompt(tag_attrs, body_attrs, i=None if exclude_id else self.id)

    def to_citation(self) -> Citation:
        return Citation(
            id=self.id,
            title=self.chunk.title,
            snippet=self.chunk.text,
            link=self.chunk.resource_id,
            updated_at=timestamp_to_datetime(self.chunk.updated_at),
            source=self.source,
        )

    def __eq__(self, other):
        if not isinstance(other, ResourceChunkRetrieval):
            return False
        return self.chunk.chunk_id == other.chunk.chunk_id
