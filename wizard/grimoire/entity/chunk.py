import time
from enum import Enum
from typing import Optional, Literal

import shortuuid
from pydantic import BaseModel, Field

from wizard.grimoire.entity.retrieval import BaseRetrieval, Citation


class ChunkType(str, Enum):
    title: str = "title"  # document title
    doc: str = "doc"  # Whole document
    section: str = "section"  # Part of document
    snippet: str = "snippet"  # Part of section
    keyword: str = "keyword"


class Chunk(BaseModel):
    title: str
    element_id: str
    text: str = Field(description="Chunk content")
    chunk_type: ChunkType = Field(description="Chunk type")

    namespace: str

    chunk_id: str = Field(description="ID of chunk", default_factory=shortuuid.uuid)
    created_timestamp: float = Field(description="Unix timestamp in float format", default_factory=time.time)

    start_lineno: Optional[int] = Field(description="The start line number of this chunk, line included", default=None)
    end_lineno: Optional[int] = Field(description="The end line number of this chunk, line excluded", default=None)
    parent_chunk_id: Optional[str] = Field(description="A chunk could be split into many smaller chunks", default=None)

    @property
    def metadata(self) -> dict:
        return {k: v for k, v in self.model_dump(exclude_none=True).items() if k not in ["chunk_id", "text"]}


class TextRetrieval(BaseRetrieval):
    retrieval_type: Literal["text"] = "text"
    chunk: Chunk

    def to_prompt(self) -> str:
        return self.chunk.text

    def to_citation(self) -> Citation:
        return Citation(
            title=self.chunk.title,
            snippet=self.chunk.text,
            link=f"{self.chunk.element_id}[{self.chunk.start_lineno}:{self.chunk.end_lineno}]"
        )
