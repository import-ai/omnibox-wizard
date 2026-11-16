import asyncio

from pydantic import BaseModel, Field

from wizard_common.grimoire.entity.index_record import IndexRecord
from wizard_common.grimoire.retriever.weaviate_vector_db import WeaviateVectorDB


class SnapshotRequest(BaseModel):
    query: str = Field(min_length=1)
    namespace_id: str
    user_id: str
    resource_ids: list[str] | None = None
    recall_depth: int = Field(default=200, ge=1, le=400)
    timeout_ms: int = Field(default=9000, ge=1, le=10000)


class SnapshotResponse(BaseModel):
    records: list[IndexRecord]
    recall_truncated: bool


async def recall_snapshot(
    request: SnapshotRequest,
    db: WeaviateVectorDB,
) -> SnapshotResponse:
    async with asyncio.timeout(request.timeout_ms / 1000):
        page = await db.search_snapshot(
            query=request.query,
            namespace_id=request.namespace_id,
            user_id=request.user_id,
            depth=request.recall_depth,
            resource_ids=request.resource_ids,
        )
    return SnapshotResponse(
        records=page.records,
        recall_truncated=page.has_more,
    )
