import asyncio
import hashlib
import json
import time

from fastapi import HTTPException
from pydantic import BaseModel, Field

from wizard_common.grimoire.config import RelevanceConfig
from wizard_common.grimoire.entity.index_record import IndexRecord, IndexRecordType
from wizard_common.grimoire.retriever.relevance import RelevanceChecker
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
    relevance_enabled: bool
    policy_signature: str


class JudgeRequest(BaseModel):
    query: str
    namespace_id: str
    user_id: str
    records: list[IndexRecord] = Field(max_length=32)
    policy_signature: str
    recall_depth: int = Field(default=200, ge=1, le=400)
    timeout_ms: int = Field(default=3000, ge=1, le=10000)


class JudgeResponse(BaseModel):
    decisions: list[str]
    policy_signature: str


def policy_signature(db: WeaviateVectorDB, config: RelevanceConfig, depth: int) -> str:
    policy = config.model_dump(
        include={
            "search_enabled",
            "base_url",
            "model",
            "search_threshold",
            "search_batch_size",
            "search_timeout_sec",
        },
        mode="json",
    )
    payload = json.dumps([db.retrieval_signature, depth, policy], sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def relevance_enabled(config: RelevanceConfig) -> bool:
    return bool(config.search_enabled and config.base_url and config.model)


async def recall_snapshot(
    request: SnapshotRequest,
    db: WeaviateVectorDB,
    config: RelevanceConfig,
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
        relevance_enabled=relevance_enabled(config),
        policy_signature=policy_signature(db, config, request.recall_depth),
    )


async def judge_snapshot(
    request: JudgeRequest,
    db: WeaviateVectorDB,
    config: RelevanceConfig,
    checker: RelevanceChecker | None,
) -> JudgeResponse:
    signature = policy_signature(db, config, request.recall_depth)
    if signature != request.policy_signature:
        return JudgeResponse(decisions=[], policy_signature=signature)
    if any(
        r.type != IndexRecordType.chunk
        or not r.chunk
        or r.namespace_id != request.namespace_id
        or (r.user_id is not None and r.user_id != request.user_id)
        for r in request.records
    ):
        raise HTTPException(400, detail="invalid_search_candidate_scope")
    if not relevance_enabled(config):
        return JudgeResponse(
            decisions=["kept"] * len(request.records), policy_signature=signature
        )
    if checker is None:
        raise HTTPException(503, detail="search_judgment_unavailable")
    hard_budget = request.timeout_ms / 1000
    budget = max(0, min(config.search_timeout_sec, hard_budget) - 0.05)
    async with asyncio.timeout(hard_budget):
        result = await checker.filter_search_results(
            request.query,
            request.records,
            deadline=time.monotonic() + budget,
        )
    kept = {r.chunk.resource_id for r in result.kept if r.chunk}
    pending = {r.chunk.resource_id for r in result.pending if r.chunk}
    return JudgeResponse(
        decisions=[
            "kept"
            if r.chunk.resource_id in kept
            else "pending"
            if r.chunk.resource_id in pending
            else "rejected"
            for r in request.records
        ],
        policy_signature=signature,
    )
