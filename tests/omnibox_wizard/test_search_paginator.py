import asyncio
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest

from omnibox_wizard.wizard.search import paginator as paginator_module
from omnibox_wizard.wizard.search.paginator import (
    FilteredSearchCache,
    FilteredSearchCacheEntry,
    FilteredSearchPaginator,
)
from wizard_common.grimoire.config import RelevanceConfig
from wizard_common.grimoire.entity.chunk import Chunk, ChunkType
from wizard_common.grimoire.entity.index_record import IndexRecord, IndexRecordType
from wizard_common.grimoire.retriever.relevance import SearchFilterResult


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


def records(start, stop):
    return [search_record(f"r{index}") for index in range(start, stop)]


class FakeVectorDB:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    async def search(self, **kwargs):
        self.calls.append(kwargs)
        return self.pages.get(kwargs["offset"], [])[: kwargs["limit"]]


class FakeChecker:
    def __init__(self, judge=None):
        self.judge = judge or (lambda record: "kept")
        self.calls = []

    async def filter_search_results(
        self, query, records, *, deadline=None, index_offset=0
    ):
        self.calls.append(
            {
                "query": query,
                "deadline": deadline,
                "index_offset": index_offset,
                "records": list(records),
            }
        )
        kept = []
        pending = []
        for record in records:
            decision = self.judge(record)
            if decision == "kept":
                kept.append(record)
            elif decision == "pending":
                pending.append(record)
        return SearchFilterResult(kept=kept, pending=pending)


@pytest.mark.asyncio
async def test_vector_diagnostics_share_the_relevance_deadline():
    vector_db = FakeVectorDB({0: records(0, 2)})
    checker = FakeChecker()
    paginator = FilteredSearchPaginator(vector_db, checker, relevance_config())
    await paginator.paginate(
        query="query",
        namespace_id="ns_1",
        user_id="user",
        offset=0,
        limit=20,
    )
    assert vector_db.calls[0]["diagnostics_deadline"] == checker.calls[0]["deadline"]


class CopyingChecker(FakeChecker):
    async def filter_search_results(
        self, query, records, *, deadline=None, index_offset=0
    ):
        self.calls.append(
            {
                "query": query,
                "deadline": deadline,
                "index_offset": index_offset,
                "records": list(records),
            }
        )
        copies = [search_record(record.chunk.resource_id) for record in records]
        kept = []
        pending = []
        for record in copies:
            decision = self.judge(record)
            if decision == "kept":
                kept.append(record)
            elif decision == "pending":
                pending.append(record)
        return SearchFilterResult(kept=kept, pending=pending)


class OneKeptPerBatchChecker:
    def __init__(self):
        self.calls = []
        self.input_count = 0

    async def filter_search_results(
        self, query, records, *, deadline=None, index_offset=0
    ):
        self.calls.append(list(records))
        self.input_count += len(records)
        return SearchFilterResult(kept=list(records[:1]), pending=list(records[1:]))


class CopyingOneKeptPerBatchChecker:
    def __init__(self):
        self.calls = []
        self.input_count = 0

    async def filter_search_results(
        self, query, records, *, deadline=None, index_offset=0
    ):
        self.calls.append(list(records))
        self.input_count += len(records)
        copies = [search_record(record.chunk.resource_id) for record in records]
        return SearchFilterResult(kept=copies[:1], pending=copies[1:])


class BudgetBurningChecker(FakeChecker):
    async def filter_search_results(
        self, query, records, *, deadline=None, index_offset=0
    ):
        self.calls.append(
            {
                "query": query,
                "deadline": deadline,
                "index_offset": index_offset,
                "records": list(records),
            }
        )
        await asyncio.sleep(max(0.0, deadline - time.monotonic()) + 0.01)
        return SearchFilterResult(kept=list(records), pending=[])


class FailingOnceChecker(FakeChecker):
    def __init__(self, error):
        super().__init__()
        self.error = error

    async def filter_search_results(
        self, query, records, *, deadline=None, index_offset=0
    ):
        self.calls.append(
            {
                "query": query,
                "deadline": deadline,
                "index_offset": index_offset,
                "records": list(records),
            }
        )
        if len(self.calls) == 1:
            raise self.error
        return SearchFilterResult(kept=list(records), pending=[])


def install_span(monkeypatch):
    span = MagicMock()
    span.__enter__.return_value = span
    span.__exit__.return_value = False
    tracer = Mock()
    tracer.start_as_current_span.return_value = span
    monkeypatch.setattr(paginator_module, "tracer", tracer)
    return span


def span_attributes(span):
    return {call.args[0]: call.args[1] for call in span.set_attribute.call_args_list}


class FakeClock:
    def __init__(self, now=0.0):
        self.now = now

    def monotonic(self):
        return self.now


def install_clock(monkeypatch, clock):
    monkeypatch.setattr(
        paginator_module, "time", SimpleNamespace(monotonic=clock.monotonic)
    )


async def paginate(
    paginator,
    *,
    offset=0,
    limit=20,
    resource_ids=None,
    timeout_ms=None,
    should_stop=None,
):
    return await paginator.paginate(
        query="query",
        namespace_id="ns_1",
        user_id="user_1",
        offset=offset,
        limit=limit,
        resource_ids=resource_ids,
        timeout_ms=timeout_ms,
        should_stop=should_stop,
    )


def search_cache_key(cache):
    return cache.key(
        namespace_id="ns_1",
        user_id="user_1",
        query="query",
        conversation_ids=None,
        exclude_conversation_ids=None,
        resource_ids=None,
    )


def seed_pending(cache, pending_records):
    key = search_cache_key(cache)
    cache.put(
        key,
        FilteredSearchCacheEntry(
            pending_records=list(pending_records),
            pending_resource_ids={
                record.chunk.resource_id for record in pending_records
            },
            has_more_raw=False,
        ),
    )
    return key


@pytest.mark.asyncio
async def test_slices_confirmed_records_and_uses_fixed_window_offsets():
    all_records = records(0, 250)
    checker = FakeChecker()
    vector_db = FakeVectorDB(
        {0: all_records[:100], 100: all_records[100:200], 200: all_records[200:]}
    )
    paginator = FilteredSearchPaginator(vector_db, checker, relevance_config())

    page = await paginate(paginator, offset=5, limit=10)

    assert [record.chunk.resource_id for record in page.records] == [
        f"r{index}" for index in range(5, 15)
    ]
    assert [call["offset"] for call in vector_db.calls] == [0]
    assert vector_db.calls[0]["limit"] == 100
    assert checker.calls[0]["index_offset"] == 0
    assert page.total is None
    assert page.has_more is True


@pytest.mark.asyncio
async def test_reports_an_exact_total_after_the_raw_result_set_is_exhausted():
    all_records = records(0, 25)
    checker = FakeChecker()
    vector_db = FakeVectorDB({0: all_records})
    paginator = FilteredSearchPaginator(vector_db, checker, relevance_config())

    page = await paginate(paginator, offset=20, limit=20)

    assert [record.chunk.resource_id for record in page.records] == [
        f"r{index}" for index in range(20, 25)
    ]
    assert [call["offset"] for call in vector_db.calls] == [0]
    assert page.total == 25
    assert page.has_more is False


@pytest.mark.asyncio
async def test_reports_unknown_total_while_raw_windows_remain():
    all_records = records(0, 250)
    checker = FakeChecker()
    vector_db = FakeVectorDB(
        {0: all_records[:100], 100: all_records[100:200], 200: all_records[200:]}
    )
    paginator = FilteredSearchPaginator(vector_db, checker, relevance_config())

    page = await paginate(paginator, offset=0, limit=20)

    assert len(page.records) == 20
    assert [call["offset"] for call in vector_db.calls] == [0]
    assert page.total is None
    assert page.has_more is True


@pytest.mark.asyncio
async def test_fixed_windows_and_per_request_scan_cap(monkeypatch):
    all_records = records(0, 250)
    checker = FakeChecker()
    vector_db = FakeVectorDB(
        {0: all_records[:100], 100: all_records[100:200], 200: all_records[200:]}
    )
    paginator = FilteredSearchPaginator(vector_db, checker, relevance_config())
    span = install_span(monkeypatch)

    first = await paginate(paginator, offset=0, limit=250)

    assert [call["offset"] for call in vector_db.calls] == [0, 100]
    assert len(first.records) == 200
    assert first.total is None
    assert first.has_more is True
    attributes = span_attributes(span)
    assert attributes["search.raw_scan_capped"] is True
    assert attributes["search.budget_exhausted"] is False

    second = await paginate(paginator, offset=200, limit=50)

    assert [call["offset"] for call in vector_db.calls] == [0, 100, 200]
    assert [record.chunk.resource_id for record in second.records] == [
        f"r{index}" for index in range(200, 250)
    ]
    assert second.total == 250
    assert second.has_more is False


@pytest.mark.asyncio
async def test_deduplicates_confirmed_resources_across_windows():
    window_zero = records(0, 100)
    window_one = [search_record("r50")] + records(100, 199)
    window_two = [search_record("r199")]
    checker = FakeChecker()
    vector_db = FakeVectorDB({0: window_zero, 100: window_one, 200: window_two})
    paginator = FilteredSearchPaginator(vector_db, checker, relevance_config())

    first = await paginate(paginator, offset=0, limit=250)
    second = await paginate(paginator, offset=199, limit=1)

    assert len(first.records) == 199
    assert len({record.chunk.resource_id for record in first.records}) == 199
    assert first.total is None
    assert first.has_more is True
    assert [record.chunk.resource_id for record in second.records] == ["r199"]
    assert second.total == 200
    assert second.has_more is False
    assert [call["offset"] for call in vector_db.calls] == [0, 100, 200]


@pytest.mark.asyncio
async def test_keeps_scanning_after_a_window_with_no_kept_records():
    first_window = [search_record(f"drop{index}") for index in range(100)]
    second_window = [search_record(f"keep{index}") for index in range(5)]
    checker = FakeChecker(
        judge=lambda record: (
            "kept" if record.chunk.resource_id.startswith("keep") else "off_target"
        )
    )
    vector_db = FakeVectorDB({0: first_window, 100: second_window})
    paginator = FilteredSearchPaginator(vector_db, checker, relevance_config())

    page = await paginate(paginator, offset=0, limit=3)

    assert [record.chunk.resource_id for record in page.records] == [
        "keep0",
        "keep1",
        "keep2",
    ]
    assert [call["offset"] for call in vector_db.calls] == [0, 100]
    assert page.total is None
    assert page.has_more is True

    next_page = await paginate(paginator, offset=3, limit=3)

    assert [record.chunk.resource_id for record in next_page.records] == [
        "keep3",
        "keep4",
    ]
    assert next_page.total == 5
    assert next_page.has_more is False
    assert [call["offset"] for call in vector_db.calls] == [0, 100]


@pytest.mark.asyncio
async def test_returns_partial_results_when_the_request_budget_expires():
    first_window = records(0, 100)
    second_window = records(100, 200)

    class SlowSecondWindowVectorDB:
        def __init__(self):
            self.calls = []

        async def search(self, **kwargs):
            self.calls.append(kwargs)
            if kwargs["offset"] == 100:
                await asyncio.sleep(0.5)
            return (first_window if kwargs["offset"] == 0 else second_window)[
                : kwargs["limit"]
            ]

    vector_db = SlowSecondWindowVectorDB()
    checker = FakeChecker()
    paginator = FilteredSearchPaginator(
        vector_db, checker, relevance_config(search_timeout_sec=0.2)
    )

    page = await paginate(paginator, offset=0, limit=200)

    assert len(page.records) == 100
    assert len(vector_db.calls) == 2
    assert page.total is None
    assert page.has_more is True


@pytest.mark.asyncio
async def test_reports_more_when_cached_results_exceed_the_returned_page():
    all_records = records(0, 25)
    checker = FakeChecker()
    vector_db = FakeVectorDB({0: all_records})
    paginator = FilteredSearchPaginator(vector_db, checker, relevance_config())

    warm = await paginate(paginator, offset=0, limit=40)
    assert len(warm.records) == 25
    assert warm.total == 25

    first = await paginate(paginator, offset=0, limit=20)
    second = await paginate(paginator, offset=20, limit=20)

    assert [record.chunk.resource_id for record in first.records] == [
        f"r{index}" for index in range(20)
    ]
    assert first.has_more is True
    assert first.total is None
    assert [record.chunk.resource_id for record in second.records] == [
        f"r{index}" for index in range(20, 25)
    ]
    assert second.has_more is False
    assert second.total == 25
    assert [call["offset"] for call in vector_db.calls] == [0]


@pytest.mark.asyncio
async def test_reuses_the_cached_scan_for_later_offsets():
    all_records = records(0, 250)
    checker = FakeChecker()
    vector_db = FakeVectorDB(
        {0: all_records[:100], 100: all_records[100:200], 200: all_records[200:]}
    )
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
    all_records = records(0, 10)
    vector_db = FakeVectorDB({0: all_records})
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
    all_records = records(0, 9)

    class FilteringVectorDB:
        def __init__(self):
            self.calls = []

        async def search(self, **kwargs):
            self.calls.append(kwargs)
            allowed = set(kwargs.get("resource_ids") or ())
            matching = [
                record
                for record in all_records
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
    all_records = [search_record("r1")]
    vector_db = FakeVectorDB({0: all_records})
    paginator = FilteredSearchPaginator(
        vector_db, FakeChecker(), RelevanceConfig(search_enabled=False)
    )

    page = await paginate(paginator, offset=0, limit=20, resource_ids=["r1"])

    assert page.records == all_records
    assert vector_db.calls[0]["resource_ids"] == ["r1"]


@pytest.mark.asyncio
async def test_rescans_after_the_cache_entry_expires():
    all_records = records(0, 20)
    checker = FakeChecker()
    vector_db = FakeVectorDB({0: all_records})
    cache = FilteredSearchCache(ttl_seconds=0)
    paginator = FilteredSearchPaginator(
        vector_db, checker, relevance_config(), cache=cache
    )

    await paginate(paginator, offset=0, limit=10)
    await paginate(paginator, offset=0, limit=10)

    assert [call["offset"] for call in vector_db.calls] == [0, 0]


@pytest.mark.asyncio
async def test_concurrent_requests_share_one_scan():
    all_records = records(0, 20)
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
                return all_records
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
    all_records = records(0, 5)
    checker = FakeChecker()
    vector_db = FakeVectorDB({5: all_records})
    paginator = FilteredSearchPaginator(vector_db, checker, config)

    page = await paginate(paginator, offset=5, limit=20)

    assert page.records == all_records
    assert page.total is None
    assert page.has_more is False
    assert vector_db.calls[0]["offset"] == 5
    assert vector_db.calls[0]["limit"] == 20
    assert checker.calls == []


@pytest.mark.asyncio
async def test_pending_is_refilled_before_new_raw_records():
    all_records = records(0, 5)
    phase = ["raw"]

    def judge(record):
        if phase[0] == "refill":
            return "kept"
        resource_id = record.chunk.resource_id
        if resource_id == "r0":
            return "pending"
        return "kept" if resource_id == "r1" else "off_target"

    checker = FakeChecker(judge=judge)
    vector_db = FakeVectorDB({0: all_records})
    paginator = FilteredSearchPaginator(vector_db, checker, relevance_config())

    first = await paginate(paginator, offset=0, limit=1)
    phase[0] = "refill"
    second = await paginate(paginator, offset=1, limit=1)

    assert [record.chunk.resource_id for record in first.records] == ["r1"]
    assert first.total is None
    assert first.has_more is True
    assert [record.chunk.resource_id for record in second.records] == ["r0"]
    assert len(checker.calls) == 2
    assert [record.chunk.resource_id for record in checker.calls[1]["records"]] == [
        "r0"
    ]
    assert [call["offset"] for call in vector_db.calls] == [0]


@pytest.mark.asyncio
async def test_confirmed_only_offset_and_total_with_pending():
    all_records = records(0, 6)

    def judge(record):
        index = int(record.chunk.resource_id[1:])
        return "pending" if index % 2 == 0 else "kept"

    checker = FakeChecker(judge=judge)
    vector_db = FakeVectorDB({0: all_records})
    paginator = FilteredSearchPaginator(vector_db, checker, relevance_config())

    first = await paginate(paginator, offset=0, limit=2)
    second = await paginate(paginator, offset=2, limit=2)

    assert [record.chunk.resource_id for record in first.records] == ["r1", "r3"]
    assert first.total is None
    assert first.has_more is True
    assert [record.chunk.resource_id for record in second.records] == ["r5"]
    assert second.total is None
    assert second.has_more is True

    checker.judge = lambda record: "kept"
    third = await paginate(paginator, offset=0, limit=10)

    assert [record.chunk.resource_id for record in third.records] == [
        "r1",
        "r3",
        "r5",
        "r0",
        "r2",
        "r4",
    ]
    assert third.total == 6
    assert third.has_more is False


@pytest.mark.asyncio
async def test_dedupes_resources_before_calling_relevance():
    all_records = [
        search_record("r0"),
        search_record("r0"),
        search_record("r1"),
        search_record("r1"),
        search_record("r2"),
    ]
    checker = FakeChecker()
    vector_db = FakeVectorDB({0: all_records})
    paginator = FilteredSearchPaginator(vector_db, checker, relevance_config())

    page = await paginate(paginator, offset=0, limit=10)

    assert [record.chunk.resource_id for record in page.records] == [
        "r0",
        "r1",
        "r2",
    ]
    assert [
        [record.chunk.resource_id for record in call["records"]]
        for call in checker.calls
    ] == [["r0", "r1", "r2"]]
    assert page.total == 3
    assert page.has_more is False


@pytest.mark.asyncio
async def test_dedupes_resources_within_a_cached_window_across_requests():
    all_records = (
        [search_record("r0")]
        + records(1, 50)
        + [search_record("r0")]
        + records(50, 100)
    )
    checker = FakeChecker()
    vector_db = FakeVectorDB({0: all_records[:100], 100: all_records[100:]})
    paginator = FilteredSearchPaginator(vector_db, checker, relevance_config())
    stop_calls = 0

    async def should_stop():
        nonlocal stop_calls
        stop_calls += 1
        return stop_calls >= 3

    first = await paginate(paginator, offset=0, limit=100, should_stop=should_stop)
    second = await paginate(paginator, offset=0, limit=100)

    assert len(first.records) == 32
    assert len(checker.calls) == 5
    assert all(
        "r0" not in [record.chunk.resource_id for record in call["records"]]
        for call in checker.calls[1:]
    )
    assert len(second.records) == 100
    assert second.total == 100
    assert second.has_more is False


@pytest.mark.asyncio
async def test_pending_cap_drops_tail_and_frees_resources_for_later_windows():
    first_window = records(0, 100)
    later_resource = search_record("r1")
    second_window = [later_resource, search_record("later")]
    checker = FakeChecker(judge=lambda record: "pending")
    vector_db = FakeVectorDB({0: first_window, 100: second_window})
    cache = FilteredSearchCache(max_pending_records=1)
    paginator = FilteredSearchPaginator(
        vector_db, checker, relevance_config(), cache=cache
    )
    stop_calls = 0

    async def should_stop():
        nonlocal stop_calls
        stop_calls += 1
        return stop_calls >= 3

    first = await paginate(paginator, offset=0, limit=10, should_stop=should_stop)

    assert [call["offset"] for call in vector_db.calls] == [0]
    assert first.records == []
    assert first.has_more is True
    assert (
        len(
            paginator.cache.get(
                paginator.cache.key(
                    namespace_id="ns_1",
                    user_id="user_1",
                    query="query",
                    conversation_ids=None,
                    exclude_conversation_ids=None,
                    resource_ids=None,
                )
            ).pending_records
        )
        == 1
    )

    checker.judge = lambda record: "kept"
    second = await paginate(paginator, offset=0, limit=1000)

    assert any(record is later_resource for record in second.records)
    assert [call["offset"] for call in vector_db.calls] == [0, 100]
    assert second.total == 71
    assert second.has_more is False


@pytest.mark.asyncio
async def test_pending_no_progress_breaks_without_spinning():
    all_records = records(0, 2)
    checker = FakeChecker(judge=lambda record: "pending")
    vector_db = FakeVectorDB({0: all_records})
    cache = FilteredSearchCache()
    paginator = FilteredSearchPaginator(
        vector_db, checker, relevance_config(), cache=cache
    )
    key = cache.key(
        namespace_id="ns_1",
        user_id="user_1",
        query="query",
        conversation_ids=None,
        exclude_conversation_ids=None,
        resource_ids=None,
    )
    cache.put(
        key,
        FilteredSearchCacheEntry(
            pending_records=all_records,
            pending_resource_ids={"r0", "r1"},
            has_more_raw=False,
        ),
    )

    first = await paginate(paginator, offset=0, limit=10)
    second = await paginate(paginator, offset=0, limit=10)

    assert len(checker.calls) == 2
    assert first.records == []
    assert second.records == []
    assert first.has_more is True
    assert second.has_more is True
    assert vector_db.calls == []


@pytest.mark.asyncio
async def test_timeout_ms_bounds_the_relevance_budget(monkeypatch):
    all_records = records(0, 100)
    checker = BudgetBurningChecker()
    vector_db = FakeVectorDB({0: all_records})
    paginator = FilteredSearchPaginator(
        vector_db, checker, relevance_config(search_timeout_sec=10)
    )
    span = install_span(monkeypatch)

    page = await paginate(paginator, offset=0, limit=100, timeout_ms=500)

    assert len(page.records) == 32
    assert page.total is None
    assert page.has_more is True
    assert len(checker.calls) == 1
    assert len(vector_db.calls) == 1
    attributes = span_attributes(span)
    assert attributes["search.budget_exhausted"] is True
    assert attributes["search.raw_scan_capped"] is False


@pytest.mark.asyncio
async def test_should_stop_prevents_further_raw_work(monkeypatch):
    all_records = records(0, 10)
    checker = FakeChecker()
    vector_db = FakeVectorDB({0: all_records})
    paginator = FilteredSearchPaginator(vector_db, checker, relevance_config())
    span = install_span(monkeypatch)

    async def should_stop():
        return True

    page = await paginate(paginator, offset=0, limit=10, should_stop=should_stop)

    assert vector_db.calls == []
    assert checker.calls == []
    assert page.records == []
    assert page.has_more is True
    attributes = span_attributes(span)
    assert attributes["search.stopped_by_client"] is True


@pytest.mark.asyncio
async def test_should_stop_errors_do_not_crash_the_search():
    all_records = records(0, 3)
    checker = FakeChecker()
    vector_db = FakeVectorDB({0: all_records})
    paginator = FilteredSearchPaginator(vector_db, checker, relevance_config())

    async def should_stop():
        raise RuntimeError("disconnect check failed")

    page = await paginate(paginator, offset=0, limit=10, should_stop=should_stop)

    assert [record.chunk.resource_id for record in page.records] == [
        "r0",
        "r1",
        "r2",
    ]
    assert page.has_more is False


@pytest.mark.asyncio
async def test_span_attributes_report_pending_confirmed_and_raw_counts(monkeypatch):
    all_records = records(0, 5)

    def judge(record):
        if record.chunk.resource_id == "r0":
            return "pending"
        return "kept" if record.chunk.resource_id == "r1" else "off_target"

    checker = FakeChecker(judge=judge)
    vector_db = FakeVectorDB({0: all_records})
    paginator = FilteredSearchPaginator(vector_db, checker, relevance_config())
    span = install_span(monkeypatch)

    await paginate(paginator, offset=0, limit=1)

    attributes = span_attributes(span)
    assert attributes["search.pending_count"] == 1
    assert attributes["search.confirmed_count"] == 1
    assert attributes["search.raw_windows_fetched"] == 1
    assert attributes["search.raw_pages_scanned"] == 1
    assert attributes["search.raw_pages_scanned_total"] == 1
    assert attributes["search.raw_records_scanned"] == 5
    assert attributes["search.pending_dropped"] == 0
    assert attributes["search.cache_hit"] is False
    assert attributes["search.budget_exhausted"] is False
    assert attributes["search.raw_scan_capped"] is False
    assert attributes["search.stopped_by_client"] is False
    assert attributes["search.has_more"] is True


@pytest.mark.asyncio
async def test_pending_refill_judges_each_record_at_most_once_per_request(monkeypatch):
    pending = records(0, 193)
    checker = OneKeptPerBatchChecker()
    cache = FilteredSearchCache()
    paginator = FilteredSearchPaginator(
        FakeVectorDB({}), checker, relevance_config(), cache=cache
    )
    seed_pending(cache, pending)
    span = install_span(monkeypatch)

    first = await paginate(paginator, offset=0, limit=200)

    assert len(checker.calls) == 7
    assert checker.input_count == 193
    assert len(first.records) == 7
    assert first.has_more is True
    assert span_attributes(span)["search.pending_count"] == 186

    page = first
    for _ in range(200):
        page = await paginate(paginator, offset=0, limit=200)
        if not page.has_more:
            break

    assert page.has_more is False
    assert page.total == 193
    assert len(page.records) == 193
    assert len({record.chunk.resource_id for record in page.records}) == 193


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [RuntimeError("checker failed"), asyncio.CancelledError()],
    ids=["error", "cancelled"],
)
async def test_retries_the_raw_slice_when_the_checker_fails(error):
    all_records = records(0, 200)
    checker = FailingOnceChecker(error)
    vector_db = FakeVectorDB({0: all_records[:100], 100: all_records[100:]})
    paginator = FilteredSearchPaginator(vector_db, checker, relevance_config())

    with pytest.raises(type(error)):
        await paginate(paginator, offset=0, limit=10)

    page = await paginate(paginator, offset=0, limit=10)

    assert [record.chunk.resource_id for record in checker.calls[1]["records"]] == [
        f"r{index}" for index in range(32)
    ]
    assert [record.chunk.resource_id for record in page.records] == [
        f"r{index}" for index in range(10)
    ]
    assert [call["offset"] for call in vector_db.calls] == [0]


@pytest.mark.asyncio
async def test_classifies_checker_copies_by_resource_id():
    all_records = records(0, 3)

    def judge(record):
        if record.chunk.resource_id == "r0":
            return "pending"
        return "kept"

    checker = CopyingChecker(judge=judge)
    vector_db = FakeVectorDB({0: all_records})
    paginator = FilteredSearchPaginator(vector_db, checker, relevance_config())

    first = await paginate(paginator, offset=0, limit=10)

    assert [record.chunk.resource_id for record in first.records] == ["r1", "r2"]
    assert first.total is None
    assert first.has_more is True

    checker.judge = lambda record: "kept"
    second = await paginate(paginator, offset=2, limit=10)

    assert [record.chunk.resource_id for record in second.records] == ["r0"]
    assert second.total == 3
    assert second.has_more is False


@pytest.mark.asyncio
async def test_skips_later_window_chunks_of_pending_resources():
    first_window = records(0, 100)
    duplicate = search_record("r0")
    second_window = [duplicate] + records(100, 140)
    checker = FakeChecker(
        judge=lambda record: "pending" if record.chunk.resource_id == "r0" else "kept"
    )
    vector_db = FakeVectorDB({0: first_window, 100: second_window})
    paginator = FilteredSearchPaginator(vector_db, checker, relevance_config())

    page = await paginate(paginator, offset=0, limit=120)

    judged_ids = [
        record.chunk.resource_id for call in checker.calls for record in call["records"]
    ]
    assert judged_ids.count("r0") == 1
    assert all(duplicate not in call["records"] for call in checker.calls)
    assert len(page.records) == 120
    assert page.total is None


@pytest.mark.asyncio
async def test_pending_cap_keeps_head_and_reports_dropped(monkeypatch):
    pending = records(0, 250)
    checker = FakeChecker(judge=lambda record: "pending")
    cache = FilteredSearchCache()
    paginator = FilteredSearchPaginator(
        FakeVectorDB({}), checker, relevance_config(), cache=cache
    )
    key = seed_pending(cache, pending)
    span = install_span(monkeypatch)

    page = await paginate(paginator, offset=0, limit=10)

    entry = cache.get(key)
    assert len(entry.pending_records) == 200
    assert [record.chunk.resource_id for record in entry.pending_records[:5]] == [
        "r0",
        "r1",
        "r2",
        "r3",
        "r4",
    ]
    assert entry.pending_records[-1].chunk.resource_id == "r199"
    assert page.records == []
    assert page.has_more is True
    assert span_attributes(span)["search.pending_dropped"] > 0
    assert len(checker.calls) == 7
    assert sum(len(call["records"]) for call in checker.calls) == 200


@pytest.mark.asyncio
async def test_advances_past_a_slice_of_duplicate_chunks_without_judging(monkeypatch):
    unique = records(0, 32)
    duplicates = [search_record(f"r{index % 32}") for index in range(64)]
    checker = FakeChecker()
    vector_db = FakeVectorDB({0: unique + duplicates})
    paginator = FilteredSearchPaginator(vector_db, checker, relevance_config())
    span = install_span(monkeypatch)

    page = await paginate(paginator, offset=0, limit=40, timeout_ms=1000)

    assert len(checker.calls) == 1
    assert [record.chunk.resource_id for record in page.records] == [
        f"r{index}" for index in range(32)
    ]
    assert page.total == 32
    assert page.has_more is False
    assert [call["offset"] for call in vector_db.calls] == [0]
    entry = paginator.cache.get(search_cache_key(paginator.cache))
    assert entry.raw_cursor == 96
    attributes = span_attributes(span)
    assert attributes["search.raw_records_scanned"] == 96
    assert attributes["search.raw_windows_fetched"] == 1
    assert attributes["search.budget_exhausted"] is False


@pytest.mark.asyncio
async def test_pending_refill_keys_checker_copies_by_resource_id(monkeypatch):
    pending = records(0, 193)
    checker = CopyingOneKeptPerBatchChecker()
    cache = FilteredSearchCache()
    paginator = FilteredSearchPaginator(
        FakeVectorDB({}), checker, relevance_config(), cache=cache
    )
    seed_pending(cache, pending)
    span = install_span(monkeypatch)

    first = await paginate(paginator, offset=0, limit=200)

    assert len(checker.calls) == 7
    assert checker.input_count == 193
    assert len(first.records) == 7
    assert first.has_more is True
    assert span_attributes(span)["search.pending_count"] == 186


@pytest.mark.asyncio
async def test_vector_search_consuming_the_budget_skips_relevance(monkeypatch):
    clock = FakeClock()
    install_clock(monkeypatch, clock)
    all_records = records(0, 10)

    class ClockAdvancingVectorDB:
        def __init__(self):
            self.calls = []

        async def search(self, **kwargs):
            self.calls.append(kwargs)
            clock.now += 2.0
            return all_records[: kwargs["limit"]]

    checker = FakeChecker()
    vector_db = ClockAdvancingVectorDB()
    paginator = FilteredSearchPaginator(
        vector_db, checker, relevance_config(search_timeout_sec=10)
    )
    span = install_span(monkeypatch)

    page = await paginate(paginator, offset=0, limit=10, timeout_ms=1000)

    assert page.records == []
    assert page.total is None
    assert page.has_more is True
    assert checker.calls == []
    assert len(vector_db.calls) == 1
    attributes = span_attributes(span)
    assert attributes["search.budget_exhausted"] is True
    assert attributes["search.raw_scan_capped"] is False


@pytest.mark.asyncio
async def test_timeout_ms_zero_exhausts_the_budget_before_any_work(monkeypatch):
    checker = FakeChecker()
    vector_db = FakeVectorDB({0: records(0, 10)})
    paginator = FilteredSearchPaginator(vector_db, checker, relevance_config())
    span = install_span(monkeypatch)

    page = await paginate(paginator, offset=0, limit=10, timeout_ms=0)

    assert page.records == []
    assert page.total is None
    assert page.has_more is True
    assert checker.calls == []
    assert vector_db.calls == []
    attributes = span_attributes(span)
    assert attributes["search.budget_exhausted"] is True
    assert attributes["search.raw_scan_capped"] is False


@pytest.mark.asyncio
async def test_judges_a_later_chunk_when_the_first_occurrence_was_off_target():
    first_occurrence = search_record("r0")
    later_occurrence = search_record("r0")
    later_occurrence.chunk.text = "later occurrence"
    first_window = [first_occurrence] + records(1, 100)
    second_window = [later_occurrence] + records(100, 102)
    checker = FakeChecker(
        judge=lambda record: (
            "kept"
            if record.chunk.resource_id != "r0"
            or record.chunk.text == "later occurrence"
            else "off_target"
        )
    )
    vector_db = FakeVectorDB({0: first_window, 100: second_window})
    paginator = FilteredSearchPaginator(vector_db, checker, relevance_config())

    page = await paginate(paginator, offset=0, limit=101)

    assert len(page.records) == 101
    assert any(record is later_occurrence for record in page.records)
    assert all(record is not first_occurrence for record in page.records)


@pytest.mark.asyncio
async def test_should_stop_on_the_pending_refill_loop(monkeypatch):
    pending = records(0, 3)
    checker = FakeChecker()
    cache = FilteredSearchCache()
    paginator = FilteredSearchPaginator(
        FakeVectorDB({}), checker, relevance_config(), cache=cache
    )
    seed_pending(cache, pending)
    span = install_span(monkeypatch)

    async def should_stop():
        return True

    page = await paginate(paginator, offset=0, limit=10, should_stop=should_stop)

    assert checker.calls == []
    assert page.records == []
    assert page.has_more is True
    assert span_attributes(span)["search.stopped_by_client"] is True


@pytest.mark.asyncio
async def test_boundary_at_one_hundred_confirmed_and_trailing_empty_window():
    all_records = records(0, 100)
    checker = FakeChecker()
    vector_db = FakeVectorDB({0: all_records, 100: []})
    paginator = FilteredSearchPaginator(vector_db, checker, relevance_config())

    first = await paginate(paginator, offset=80, limit=20)

    assert [record.chunk.resource_id for record in first.records] == [
        f"r{index}" for index in range(80, 100)
    ]
    assert first.total is None
    assert first.has_more is True
    assert [call["offset"] for call in vector_db.calls] == [0]

    second = await paginate(paginator, offset=100, limit=20)

    assert second.records == []
    assert second.total == 100
    assert second.has_more is False
    assert [call["offset"] for call in vector_db.calls] == [0, 100]
