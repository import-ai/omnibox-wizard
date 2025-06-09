from enum import Enum
from pydantic import BaseModel

from wizard.grimoire.entity.chunk import Chunk

class IndexRecordType(str, Enum):
    chunk = "chunk"
    message = "message"


class IndexRecord(BaseModel):
    id: str
    type: IndexRecordType
    chunk: Chunk | None
