import time
from datetime import datetime
from enum import Enum
from typing import Optional

import shortuuid
from pydantic import BaseModel, Field

from src.common.utils import remove_continuous_break_lines
from src.wizard.grimoire.entity.retrieval import BaseRetrieval, Citation


class ChunkType(str, Enum):
    title: str = "title"  # document title
    doc: str = "doc"  # Whole document
    snippet: str = "snippet"  # Part of section
    keyword: str = "keyword"


def timestamp_to_datetime(timestamp: float, date_format: str = "%Y-%m-%d %H:%M:%S") -> str:
    return datetime.fromtimestamp(timestamp).strftime(date_format)


class Chunk(BaseModel):
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


class ResourceChunkRetrieval(BaseRetrieval):
    folder: str | None = Field(default=None, description="The folder of the chunk, if any")
    chunk: Chunk

    def source(self) -> str:
        return "private"

    def to_prompt(self) -> str:
        contents: list[str] = []
        citation = self.to_citation()

        if self.folder:
            contents.append(f"<folder>{self.folder}</folder>")
        if citation.title:
            contents.append(f"<title>{citation.title}</title>")
        if citation.snippet:
            contents.append(f"<snippet>{citation.snippet}</snippet>")
        if citation.updated_at:
            contents.append(f"<updated_at>{citation.updated_at}</updated_at>")
        return remove_continuous_break_lines("\n".join(contents))

    def to_citation(self) -> Citation:
        return Citation(
            title=self.chunk.title,
            snippet=self.chunk.text,
            link=self.chunk.resource_id,
            updated_at=timestamp_to_datetime(self.chunk.updated_at)
        )
