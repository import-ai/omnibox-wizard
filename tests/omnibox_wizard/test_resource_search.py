from unittest.mock import AsyncMock

import httpx
import pytest

from wizard_common.grimoire.retriever.resource_search import ResourceSearch
from wizard_common.grimoire.retriever.visible_client import (
    BackendVisibleBaseClient,
    BackendVisibleClient,
)
from wizard_common.grimoire.entity.chunk import Chunk, ChunkType, ResourceChunkRetrieval
from wizard_common.grimoire.entity.retrieval import Score
from wizard_common.grimoire.entity.tools import (
    PrivateSearchResourceType,
    PrivateSearchTool,
    Resource,
)
from wizard_common.grimoire.retriever.weaviate_vector_db import WeaviateVectorRetriever


def make_retrieval(resource_id: str) -> ResourceChunkRetrieval:
    return ResourceChunkRetrieval(
        chunk=Chunk(
            title=resource_id,
            resource_id=resource_id,
            text=f"snippet for {resource_id}",
            chunk_type=ChunkType.snippet,
            parent_id="parent",
        ),
        namespace_id="ns",
        score=Score(recall=1.0, rerank=0),
    )


def private_search_tool(visible_ids: list[str] | None) -> PrivateSearchTool:
    visible_resources = None
    if visible_ids is not None:
        visible_resources = [
            Resource(
                id=resource_id,
                name=resource_id,
                type=PrivateSearchResourceType.RESOURCE,
            )
            for resource_id in visible_ids
        ]
    return PrivateSearchTool(
        namespace_id="ns",
        visible_resources=visible_resources,
    )


class FakeVisibleClient(BackendVisibleBaseClient):
    def __init__(self, visible: list[str], error: Exception | None = None):
        self.visible = visible
        self.error = error
        self.requested: list[list[str]] = []

    async def filter_visible_resource_ids(self, resource_ids: list[str]) -> list[str]:
        self.requested.append(resource_ids)
        if self.error:
            raise self.error
        allowed = set(self.visible)
        return [resource_id for resource_id in resource_ids if resource_id in allowed]


async def fake_query(_self, _query, k, *, private_search_tool, trace_info=None):
    del private_search_tool, trace_info
    fake_query.k = k
    return fake_query.retrievals


async def run_query(*, visible_ids, hits, client):
    fake_query.retrievals = [make_retrieval(resource_id) for resource_id in hits]
    search = ResourceSearch.__new__(ResourceSearch)
    return await search.query(
        "weather",
        private_search_tool=private_search_tool(visible_ids),
        backend_client=client,
    )


@pytest.mark.asyncio
async def test_empty_visible_resources_oversamples_and_drops_unauthorized(monkeypatch):
    monkeypatch.setattr(WeaviateVectorRetriever, "query", fake_query)
    client = FakeVisibleClient(["keep-1", "keep-2"])

    retrievals = await run_query(
        visible_ids=[],
        hits=["keep-1", "deny", "keep-2"],
        client=client,
    )

    assert fake_query.k == ResourceSearch.EMPTY_OVERSAMPLE
    assert [item.chunk.resource_id for item in retrievals] == ["keep-1", "keep-2"]
    assert client.requested == [["keep-1", "deny", "keep-2"]]


@pytest.mark.asyncio
async def test_scoped_visible_resources_oversample_then_acl(monkeypatch):
    monkeypatch.setattr(WeaviateVectorRetriever, "query", fake_query)
    client = FakeVisibleClient(["keep"])

    retrievals = await run_query(
        visible_ids=["keep"],
        hits=["keep", "stale"],
        client=client,
    )

    assert fake_query.k == ResourceSearch.SCOPED_OVERSAMPLE
    assert [item.chunk.resource_id for item in retrievals] == ["keep"]


@pytest.mark.asyncio
async def test_query_fail_closed_when_visible_check_fails(monkeypatch):
    monkeypatch.setattr(WeaviateVectorRetriever, "query", fake_query)
    client = FakeVisibleClient(["keep"], error=RuntimeError("backend down"))

    retrievals = await run_query(
        visible_ids=[],
        hits=["keep"],
        client=client,
    )

    assert retrievals == []


@pytest.mark.asyncio
async def test_query_fail_closed_without_backend_client(monkeypatch):
    monkeypatch.setattr(WeaviateVectorRetriever, "query", fake_query)
    fake_query.retrievals = [make_retrieval("keep")]
    search = ResourceSearch.__new__(ResourceSearch)

    retrievals = await search.query(
        "weather",
        private_search_tool=private_search_tool([]),
    )

    assert retrievals == []


@pytest.mark.asyncio
async def test_query_requires_visible_resources(monkeypatch):
    monkeypatch.setattr(WeaviateVectorRetriever, "query", fake_query)
    search = ResourceSearch.__new__(ResourceSearch)
    tool = PrivateSearchTool.model_construct(
        namespace_id="ns",
        visible_resources=None,
    )

    try:
        await search.query(
            "weather",
            private_search_tool=tool,
            backend_client=FakeVisibleClient([]),
        )
    except AssertionError as exc:
        assert "visible_resources" in str(exc)
    else:
        raise AssertionError("expected AssertionError")


@pytest.mark.asyncio
async def test_query_truncates_to_result_limit(monkeypatch):
    monkeypatch.setattr(WeaviateVectorRetriever, "query", fake_query)
    hits = [f"doc-{i}" for i in range(ResourceSearch.RESULT_LIMIT + 5)]
    client = FakeVisibleClient(hits)

    retrievals = await run_query(visible_ids=[], hits=hits, client=client)

    assert len(retrievals) == ResourceSearch.RESULT_LIMIT
    assert retrievals[0].chunk.resource_id == "doc-0"
    assert retrievals[-1].chunk.resource_id == "doc-39"


@pytest.mark.asyncio
async def test_share_client_keeps_hits_without_namespace_acl(monkeypatch):
    monkeypatch.setattr(WeaviateVectorRetriever, "query", fake_query)
    client = BackendVisibleBaseClient()

    retrievals = await run_query(
        visible_ids=[],
        hits=["shared-1", "shared-2"],
        client=client,
    )

    assert [item.chunk.resource_id for item in retrievals] == [
        "shared-1",
        "shared-2",
    ]


def make_response(status_code: int, json: dict) -> httpx.Response:
    return httpx.Response(
        status_code,
        json=json,
        request=httpx.Request("POST", "http://test/resources/visible"),
    )


def patch_request(monkeypatch, side_effect) -> AsyncMock:
    mock = AsyncMock(side_effect=side_effect)
    monkeypatch.setattr(httpx.AsyncClient, "request", mock)
    return mock


@pytest.mark.asyncio
async def test_filter_visible_resource_ids_posts_unique_ids(monkeypatch):
    client = BackendVisibleClient(
        base_url="http://test",
        user_id="user-1",
        namespace_id="ns-1",
    )
    request_mock = patch_request(
        monkeypatch, [make_response(200, {"resource_ids": ["keep"]})]
    )

    result = await client.filter_visible_resource_ids(["keep", "keep", "deny"])

    assert result == ["keep"]
    assert request_mock.await_count == 1
    assert request_mock.await_args.args[0] == "POST"
    assert request_mock.await_args.args[1].endswith("/resources/visible")
    assert request_mock.await_args.kwargs["json"] == {"resource_ids": ["keep", "deny"]}


@pytest.mark.asyncio
async def test_filter_visible_resource_ids_skips_empty_post(monkeypatch):
    client = BackendVisibleClient(
        base_url="http://test",
        user_id="user-1",
        namespace_id="ns-1",
    )
    request_mock = patch_request(monkeypatch, [])

    assert await client.filter_visible_resource_ids([]) == []
    request_mock.assert_not_awaited()


def test_get_type_defaults_to_resource_when_visible_resources_empty():
    resource = Resource.model_validate(
        {
            "id": "doc-1",
            "name": "My doc",
            "type": WeaviateVectorRetriever.get_type("doc-1", []),
        }
    )
    assert resource.type is PrivateSearchResourceType.RESOURCE


def test_get_type_uses_visible_resource_when_present():
    resources = [
        Resource(id="folder-1", name="f", type=PrivateSearchResourceType.FOLDER),
    ]
    assert (
        WeaviateVectorRetriever.get_type("folder-1", resources)
        is PrivateSearchResourceType.FOLDER
    )
