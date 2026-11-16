import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

from omnibox_wizard.wizard.search.snapshot import (
    SnapshotRequest,
    recall_snapshot,
)
from wizard_common.grimoire.entity.index_record import IndexRecord, IndexRecordType
from wizard_common.grimoire.retriever.weaviate_vector_db import VectorSearchPage


def record(resource_id="a", namespace="n"):
    return IndexRecord(
        type=IndexRecordType.chunk,
        namespace_id=namespace,
        chunk={
            "resource_id": resource_id,
            "parent_id": "root",
            "chunk_id": resource_id,
            "title": "t",
            "text": "text",
            "chunk_type": "doc",
        },
    )


@pytest.mark.asyncio
async def test_snapshot_returns_all_candidates_without_judgment():
    db = Mock()
    db.search_snapshot = AsyncMock(
        return_value=VectorSearchPage(records=[record()], has_more=True)
    )
    result = await recall_snapshot(
        SnapshotRequest(query="q", namespace_id="n", user_id="u"), db
    )
    assert len(result.records) == 1
    assert result.recall_truncated
    db.search_snapshot.assert_awaited_once()


@pytest.mark.asyncio
async def test_snapshot_deadline_cancels_recall():
    db = Mock()

    async def slow(**_):
        await asyncio.sleep(10)

    db.search_snapshot = AsyncMock(side_effect=slow)
    with pytest.raises(TimeoutError):
        await recall_snapshot(
            SnapshotRequest(query="q", namespace_id="n", user_id="u", timeout_ms=1),
            db,
        )
