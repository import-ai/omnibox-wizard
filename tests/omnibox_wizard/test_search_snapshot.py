import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

from omnibox_wizard.wizard.search.snapshot import (
    JudgeRequest,
    SnapshotRequest,
    judge_snapshot,
    policy_signature,
    recall_snapshot,
)
from wizard_common.grimoire.config import RelevanceConfig
from wizard_common.grimoire.entity.index_record import IndexRecord, IndexRecordType
from wizard_common.grimoire.retriever.relevance import SearchFilterResult
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
async def test_snapshot_returns_all_candidates_and_policy_without_judgment():
    db = Mock(retrieval_signature="v2")
    db.search_snapshot = AsyncMock(
        return_value=VectorSearchPage(records=[record()], has_more=True)
    )
    result = await recall_snapshot(
        SnapshotRequest(query="q", namespace_id="n", user_id="u"), db, RelevanceConfig()
    )
    assert len(result.records) == 1
    assert result.recall_truncated
    assert not result.relevance_enabled
    db.search_snapshot.assert_awaited_once()


@pytest.mark.asyncio
async def test_fixed_scope_and_policy_guard_before_judging():
    db = Mock(retrieval_signature="v2")
    checker = AsyncMock()
    config = RelevanceConfig()
    request = JudgeRequest(
        query="q",
        namespace_id="n",
        user_id="u",
        records=[record()],
        policy_signature="old",
    )
    result = await judge_snapshot(request, db, config, checker)
    assert result.policy_signature != "old"
    checker.filter_search_results.assert_not_called()
    request.policy_signature = policy_signature(db, config, 200)
    request.records = [record(namespace="other")]
    with pytest.raises(Exception) as error:
        await judge_snapshot(request, db, config, checker)
    assert error.value.status_code == 400


@pytest.mark.asyncio
async def test_judgment_preserves_per_candidate_pending_order_without_recall():
    db = Mock(retrieval_signature="v2")
    config = RelevanceConfig(base_url="http://judge", model="model")
    records = [record("a"), record("b"), record("c")]
    checker = AsyncMock()
    checker.filter_search_results.return_value = SearchFilterResult(
        kept=[records[1]], pending=[records[0]]
    )
    request = JudgeRequest(
        query="q",
        namespace_id="n",
        user_id="u",
        records=records,
        policy_signature=policy_signature(db, config, 200),
    )
    result = await judge_snapshot(request, db, config, checker)
    assert result.decisions == ["pending", "kept", "rejected"]
    db.search_snapshot.assert_not_called()


@pytest.mark.asyncio
async def test_snapshot_deadline_cancels_recall():
    db = Mock(retrieval_signature="v2")

    async def slow(**_):
        await asyncio.sleep(10)

    db.search_snapshot = AsyncMock(side_effect=slow)
    with pytest.raises(TimeoutError):
        await recall_snapshot(
            SnapshotRequest(query="q", namespace_id="n", user_id="u", timeout_ms=1),
            db,
            RelevanceConfig(),
        )
