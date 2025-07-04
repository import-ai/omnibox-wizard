from enum import Enum
from pydantic import BaseModel, Field

from omnibox_wizard.wizard.grimoire.entity.chunk import Chunk
from omnibox_wizard.wizard.grimoire.entity.message import Message


class IndexRecordType(str, Enum):
    chunk = "chunk"
    message = "message"


class IndexRecord(BaseModel):
    id: str
    type: IndexRecordType
    namespace_id: str
    user_id: str | None = None
    chunk: Chunk | None = None
    message: Message | None = None

    vectors: dict[str, list[float]] | None = Field(default=None, alias="_vectors")
