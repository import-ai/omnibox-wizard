import asyncio

import pytest

from omnibox_wizard.wizard.search.paginator import (
    FilteredSearchCache,
    FilteredSearchPaginator,
)
from wizard_common.grimoire.config import RelevanceConfig
from wizard_common.grimoire.entity.chunk import Chunk, ChunkType
from wizard_common.grimoire.entity.index_record import IndexRecord, IndexRecordType


def relevance_config(**overrides):
    return RelevanceConfig(
        **{
            "base_url": "https://judge.invalid/v1",
            "model": "decision-test",
            **overrides,
        }
    )


def search_record(resource_id):
    return IndexRecord(
        type=IndexRecordType.chunk,
        namespace_id="ns_1",
        chunk=Chunk(
            title=resource_id,
            resource_id=resource_id,
            text=f"Content for {resource_id}",
            chunk_type=ChunkType.doc,
            parent_id="parent_1",
        ),
    )


class FakeVectorDB:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    async def search(self, **kwargs):
        self.calls.append(kwargs)
        return self.pages.get(kwargs["offset"], [])[: kwargs["limit"]]


class FakeChecker:
    def __init__(self, keep=lambda record: True):
        self.keep = keep
        self.calls = []

    async def filter_search_results(
        self, query, records, *, deadline=None, index_offset=0
    ):
        self.calls.append(
            {
                "query": query,
                "deadline": deadline,
                "index_offset": index_offset,
                "count": len(records),
            }
        )
        return [record for record in records if self.keep(record)]


async def paginate(paginator, *, offset=0, limit=20, resource_ids=None):
    return await paginator.paginate(
        query="query",
        namespace_id="ns_1",
        user_id="user_1",
        offset=offset,
        limit=limit,
        resource_ids=resource_ids,
    )


@pytest.mark.asyncio
async def test_slices_filtered_records_and_uses_global_scan_offsets():
    records = [search_record(f"r{index}") for index in range(40)]
    checker = FakeChecker()
    vector_db = FakeVectorDB({0: records[:20], 20: records[20:]})
    paginator = FilteredSearchPaginator(vector_db, checker, relevance_config())

    page = await paginate(paginator, offset=5, limit=10)

    assert [record.chunk.resource_id for record in page.records] == [
        f"r{index}" for index in range(5, 15)
    ]
    assert [call["offset"] for call in vector_db.calls] == [0]
    assert checker.calls[0]["index_offset"] == 0
    assert page.total is None
    assert page.has_more is True


@pytest.mark.asyncio
async def test_reports_an_exact_total_after_the_raw_result_set_is_exhausted():
    records = [search_record(f"r{index}") for index in range(25)]
    checker = FakeChecker()
    vector_db = FakeVectorDB({0: records[:20], 20: records[20:]})
    paginator = FilteredSearchPaginator(vector_db, checker, relevance_config())

    page = await paginate(paginator, offset=20, limit=20)

    assert [record.chunk.resource_id for record in page.records] == [
        f"r{index}" for index in range(20, 25)
    ]
    assert [call["offset"] for call in vector_db.calls] == [0, 20]
    assert page.total == 25
    assert page.has_more is False


@pytest.mark.asyncio
async def test_reports_unknown_total_while_the_raw_result_set_has_more_pages():
    records = [search_record(f"r{index}") for index in range(40)]
    checker = FakeChecker()
    vector_db = FakeVectorDB({0: records[:20], 20: records[20:]})
    paginator = FilteredSearchPaginator(vector_db, checker, relevance_config())

    page = await paginate(paginator, offset=0, limit=20)

    assert len(page.records) == 20
    assert [call["offset"] for call in vector_db.calls] == [0]
    assert page.total is None
    assert page.has_more is True


@pytest.mark.asyncio
async def test_deduplicates_kept_resources_across_pages():
    first_page = [search_record(f"r{index}") for index in range(20)]
    second_page = [search_record("r19")] + [
        search_record(f"r{index}") for index in range(20, 39)
    ]
    checker = FakeChecker()
    vector_db = FakeVectorDB({0: first_page, 20: second_page, 40: []})
    paginator = FilteredSearchPaginator(vector_db, checker, relevance_config())

    page = await paginate(paginator, offset=0, limit=40)

    resource_ids = [record.chunk.resource_id for record in page.records]
    assert len(resource_ids) == 39
    assert len(set(resource_ids)) == 39
    assert resource_ids.count("r19") == 1
    assert page.total == 39
    assert page.has_more is False


@pytest.mark.asyncio
async def test_keeps_scanning_after_a_page_with_no_kept_records():
    first_page = [search_record(f"drop{index}") for index in range(20)]
    second_page = [search_record(f"keep{index}") for index in range(5)]
    checker = FakeChecker(
        keep=lambda record: record.chunk.resource_id.startswith("keep")
    )
    vector_db = FakeVectorDB({0: first_page, 20: second_page})
    paginator = FilteredSearchPaginator(vector_db, checker, relevance_config())

    page = await paginate(paginator, offset=0, limit=3)

    assert [record.chunk.resource_id for record in page.records] == [
        "keep0",
        "keep1",
        "keep2",
    ]
    assert [call["offset"] for call in vector_db.calls] == [0, 20]
    assert page.total == 5
    assert page.has_more is True

    next_page = await paginate(paginator, offset=3, limit=3)

    assert [record.chunk.resource_id for record in next_page.records] == [
        "keep3",
        "keep4",
    ]
    assert next_page.total == 5
    assert next_page.has_more is False
    assert [call["offset"] for call in vector_db.calls] == [0, 20]


@pytest.mark.asyncio
async def test_returns_partial_results_when_the_request_budget_expires():
    records = [search_record(f"r{index}") for index in range(20)]

    class SlowVectorDB:
        def __init__(self):
            self.calls = 0

        async def search(self, **kwargs):
            self.calls += 1
            await asyncio.sleep(0.1)
            return records

    vector_db = SlowVectorDB()
    checker = FakeChecker()
    paginator = FilteredSearchPaginator(
        vector_db, checker, relevance_config(search_timeout_sec=0.05)
    )

    page = await paginate(paginator, offset=0, limit=40)

    assert len(page.records) == 20
    assert vector_db.calls == 1
    assert page.total is None
    assert page.has_more is True


@pytest.mark.asyncio
async def test_reports_more_when_cached_results_exceed_the_returned_page():
    records = [search_record(f"r{index}") for index in range(25)]
    checker = FakeChecker()
    vector_db = FakeVectorDB({0: records[:20], 20: records[20:]})
    paginator = FilteredSearchPaginator(vector_db, checker, relevance_config())

    warm = await paginate(paginator, offset=0, limit=40)
    assert len(warm.records) == 25

    first = await paginate(paginator, offset=0, limit=20)
    second = await paginate(paginator, offset=20, limit=20)

    assert [record.chunk.resource_id for record in first.records] == [
        f"r{index}" for index in range(20)
    ]
    assert first.has_more is True
    assert first.total == 25
    assert [record.chunk.resource_id for record in second.records] == [
        f"r{index}" for index in range(20, 25)
    ]
    assert second.has_more is False
    assert second.total == 25
    assert [call["offset"] for call in vector_db.calls] == [0, 20]


@pytest.mark.asyncio
async def test_reuses_the_cached_scan_for_later_offsets():
    records = [search_record(f"r{index}") for index in range(40)]
    checker = FakeChecker()
    vector_db = FakeVectorDB({0: records[:20], 20: records[20:]})
    paginator = FilteredSearchPaginator(vector_db, checker, relevance_config())

    first = await paginate(paginator, offset=0, limit=10)
    second = await paginate(paginator, offset=10, limit=10)

    assert len(first.records) == 10
    assert [record.chunk.resource_id for record in second.records] == [
        f"r{index}" for index in range(10, 20)
    ]
    assert [call["offset"] for call in vector_db.calls] == [0]


@pytest.mark.asyncio
async def test_resource_filters_are_part_of_the_cache_key_and_pass_through():
    records = [search_record(f"r{index}") for index in range(10)]
    vector_db = FakeVectorDB({0: records})
    paginator = FilteredSearchPaginator(vector_db, FakeChecker(), relevance_config())

    await paginate(paginator, offset=0, limit=5, resource_ids=["r2", "r1"])
    await paginate(paginator, offset=0, limit=5, resource_ids=["r1", "r2"])
    await paginate(paginator, offset=0, limit=5, resource_ids=["r3"])

    assert [call["resource_ids"] for call in vector_db.calls] == [
        ["r2", "r1"],
        ["r3"],
    ]


def test_cache_keys_distinguish_resource_filters_but_ignore_their_order():
    cache = FilteredSearchCache()
    common = {
        "namespace_id": "ns_1",
        "user_id": "user_1",
        "query": "query",
        "conversation_ids": None,
        "exclude_conversation_ids": None,
    }

    assert cache.key(**common, resource_ids=["b", "a"]) == cache.key(
        **common, resource_ids=["a", "b"]
    )
    assert cache.key(**common, resource_ids=None) == cache.key(
        **common, resource_ids=[]
    )
    assert cache.key(**common, resource_ids=["a"]) != cache.key(
        **common, resource_ids=["a", "b"]
    )


@pytest.mark.asyncio
async def test_filtered_page_only_contains_candidate_resources():
    records = [search_record(f"r{index}") for index in range(9)]

    class FilteringVectorDB:
        def __init__(self):
            self.calls = []

        async def search(self, **kwargs):
            self.calls.append(kwargs)
            allowed = set(kwargs.get("resource_ids") or ())
            matching = [
                record
                for record in records
                if not allowed or record.chunk.resource_id in allowed
            ]
            start = kwargs["offset"]
            return matching[start : start + kwargs["limit"]]

    vector_db = FilteringVectorDB()
    paginator = FilteredSearchPaginator(vector_db, FakeChecker(), relevance_config())

    page = await paginate(
        paginator, offset=0, limit=20, resource_ids=["r1", "r4", "r7"]
    )

    assert [record.chunk.resource_id for record in page.records] == [
        "r1",
        "r4",
        "r7",
    ]
    assert page.total == 3
    assert page.has_more is False
    assert vector_db.calls[0]["resource_ids"] == ["r1", "r4", "r7"]


@pytest.mark.asyncio
async def test_raw_path_passes_resource_ids_to_the_search():
    records = [search_record("r1")]
    vector_db = FakeVectorDB({0: records})
    paginator = FilteredSearchPaginator(
        vector_db, FakeChecker(), RelevanceConfig(search_enabled=False)
    )

    page = await paginate(paginator, offset=0, limit=20, resource_ids=["r1"])

    assert page.records == records
    assert vector_db.calls[0]["resource_ids"] == ["r1"]


@pytest.mark.asyncio
async def test_rescans_after_the_cache_entry_expires():
    records = [search_record(f"r{index}") for index in range(20)]
    checker = FakeChecker()
    vector_db = FakeVectorDB({0: records})
    cache = FilteredSearchCache(ttl_seconds=0)
    paginator = FilteredSearchPaginator(
        vector_db, checker, relevance_config(), cache=cache
    )

    await paginate(paginator, offset=0, limit=10)
    await paginate(paginator, offset=0, limit=10)

    assert [call["offset"] for call in vector_db.calls] == [0, 0]


@pytest.mark.asyncio
async def test_concurrent_requests_share_one_scan():
    records = [search_record(f"r{index}") for index in range(20)]
    checker = FakeChecker()
    started = asyncio.Event()
    release = asyncio.Event()

    class GatedVectorDB:
        def __init__(self):
            self.calls = 0

        async def search(self, **kwargs):
            self.calls += 1
            if kwargs["offset"] == 0:
                started.set()
                await release.wait()
                return records
            return []

    vector_db = GatedVectorDB()
    paginator = FilteredSearchPaginator(vector_db, checker, relevance_config())

    first_task = asyncio.create_task(paginate(paginator, offset=0, limit=10))
    await started.wait()
    second_task = asyncio.create_task(paginate(paginator, offset=0, limit=10))
    await asyncio.sleep(0.01)
    release.set()
    first, second = await asyncio.gather(first_task, second_task)

    assert vector_db.calls == 1
    assert [record.chunk.resource_id for record in first.records] == [
        record.chunk.resource_id for record in second.records
    ]
    third = await paginate(paginator, offset=0, limit=40)
    assert len(third.records) == 20
    assert third.total == 20
    assert third.has_more is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "config",
    [
        RelevanceConfig(search_enabled=False),
        RelevanceConfig(),
    ],
    ids=["disabled", "unconfigured"],
)
async def test_bypasses_relevance_when_search_is_disabled_or_unconfigured(config):
    records = [search_record(f"r{index}") for index in range(5)]
    checker = FakeChecker()
    vector_db = FakeVectorDB({5: records})
    paginator = FilteredSearchPaginator(vector_db, checker, config)

    page = await paginate(paginator, offset=5, limit=20)

    assert page.records == records
    assert page.total is None
    assert page.has_more is False
    assert vector_db.calls[0]["offset"] == 5
    assert vector_db.calls[0]["limit"] == 20
    assert checker.calls == []
