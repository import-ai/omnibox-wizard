from enum import Enum
from pydantic import BaseModel, Field

from wizard.grimoire.entity.chunk import Chunk


class IndexRecordType(str, Enum):
    chunk = "chunk"
    message = "message"


class IndexRecord(BaseModel):
    id: str
    type: IndexRecordType
    namespace_id: str
    chunk: Chunk | None

    vectors: dict[str, list[float]] | None = Field(default=None, alias="_vectors")
