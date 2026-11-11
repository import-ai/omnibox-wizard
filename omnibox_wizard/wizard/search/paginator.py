import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from opentelemetry import trace

from wizard_common.grimoire.config import RelevanceConfig
from wizard_common.grimoire.entity.index_record import IndexRecord, IndexRecordType
from wizard_common.grimoire.retriever.relevance import (
    RelevanceChecker,
    SearchFilterResult,
)
from wizard_common.grimoire.retriever.weaviate_vector_db import WeaviateVectorDB

tracer = trace.get_tracer(__name__)

RAW_WINDOW_SIZE = 100
MAX_RAW_RECORDS_PER_REQUEST = 200
RELEVANCE_SLICE_SIZE = 32
CACHE_TTL_SECONDS = 30.0
CACHE_MAX_ENTRIES = 100
CACHE_MAX_FILTERED_RECORDS = 500
CACHE_MAX_PENDING_RECORDS = 200

SearchKey = tuple[
    str, str, str, str, tuple[str, ...], tuple[str, ...], tuple[str, ...], str
]


@dataclass
class SearchPage:
    records: list[IndexRecord]
    total: int | None
    has_more: bool


@dataclass
class FilteredSearchCacheEntry:
    filtered_records: list[IndexRecord] = field(default_factory=list)
    pending_records: list[IndexRecord] = field(default_factory=list)
    raw_records: list[IndexRecord] = field(default_factory=list)
    raw_window_start: int = 0
    raw_cursor: int = 0
    has_more_raw: bool = True
    seen_resource_ids: set[str] = field(default_factory=set)
    pending_resource_ids: set[str] = field(default_factory=set)
    judged_chunk_count: int = 0
    expires_at: float = 0.0
    raw_pages_scanned_total: int = 0


def _chunk_records(records: list[IndexRecord]) -> list[IndexRecord]:
    return [
        record
        for record in records
        if record.type == IndexRecordType.chunk and record.chunk is not None
    ]


def _resource_id(record: IndexRecord) -> str | None:
    if record.type != IndexRecordType.chunk or record.chunk is None:
        return None
    return record.chunk.resource_id


async def _stop_requested(
    should_stop: Callable[[], Awaitable[bool]] | None,
) -> bool:
    if should_stop is None:
        return False
    try:
        return await should_stop()
    except Exception:
        return False


class FilteredSearchCache:
    def __init__(
        self,
        ttl_seconds: float = CACHE_TTL_SECONDS,
        max_entries: int = CACHE_MAX_ENTRIES,
        max_filtered_records: int = CACHE_MAX_FILTERED_RECORDS,
        max_pending_records: int = CACHE_MAX_PENDING_RECORDS,
    ):
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self.max_filtered_records = max_filtered_records
        self.max_pending_records = max_pending_records
        self._entries: dict[SearchKey, FilteredSearchCacheEntry] = {}
        self._locks: dict[SearchKey, asyncio.Lock] = {}

    def key(
        self,
        *,
        namespace_id: str,
        user_id: str | None,
        query: str,
        conversation_ids: list[str] | None,
        exclude_conversation_ids: list[str] | None,
        resource_ids: list[str] | None = None,
        retrieval_signature: str = "",
    ) -> SearchKey:
        return (
            namespace_id,
            user_id or "",
            query,
            IndexRecordType.chunk.value,
            tuple(conversation_ids or ()),
            tuple(exclude_conversation_ids or ()),
            tuple(sorted(resource_ids or ())),
            retrieval_signature,
        )

    def lock_for(self, key: SearchKey) -> asyncio.Lock:
        lock = self._locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[key] = lock
        return lock

    def get(self, key: SearchKey) -> FilteredSearchCacheEntry | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        if entry.expires_at <= time.monotonic():
            self._entries.pop(key, None)
            return None
        self._entries.pop(key, None)
        self._entries[key] = entry
        return entry

    def put(self, key: SearchKey, entry: FilteredSearchCacheEntry) -> None:
        if len(entry.filtered_records) > self.max_filtered_records:
            self._entries.pop(key, None)
            return
        entry.expires_at = time.monotonic() + self.ttl_seconds
        self._entries.pop(key, None)
        self._entries[key] = entry
        while len(self._entries) > self.max_entries:
            oldest = next(iter(self._entries))
            self._entries.pop(oldest, None)
        for cached_key in list(self._locks):
            if cached_key not in self._entries and not self._locks[cached_key].locked():
                self._locks.pop(cached_key, None)


class FilteredSearchPaginator:
    def __init__(
        self,
        vector_db: WeaviateVectorDB,
        relevance_checker: RelevanceChecker | None,
        relevance_config: RelevanceConfig,
        cache: FilteredSearchCache | None = None,
    ):
        self.vector_db = vector_db
        self.relevance_checker = relevance_checker
        self.relevance_config = relevance_config
        self.cache = cache if cache is not None else FilteredSearchCache()

    def relevance_active(self) -> bool:
        return (
            self.relevance_config.search_enabled
            and self.relevance_checker is not None
            and bool(self.relevance_config.base_url)
            and bool(self.relevance_config.model)
        )

    async def paginate(
        self,
        *,
        query: str,
        namespace_id: str,
        user_id: str | None,
        offset: int,
        limit: int,
        conversation_ids: list[str] | None = None,
        exclude_conversation_ids: list[str] | None = None,
        resource_ids: list[str] | None = None,
        timeout_ms: int | None = None,
        should_stop: Callable[[], Awaitable[bool]] | None = None,
    ) -> SearchPage:
        with tracer.start_as_current_span("FilteredSearchPaginator.paginate") as span:
            span.set_attribute("search.offset", offset)
            span.set_attribute("search.limit", limit)
            if not self.relevance_active():
                return await self._paginate_raw(
                    span,
                    query=query,
                    namespace_id=namespace_id,
                    user_id=user_id,
                    offset=offset,
                    limit=limit,
                    conversation_ids=conversation_ids,
                    exclude_conversation_ids=exclude_conversation_ids,
                    resource_ids=resource_ids,
                )

            key = self.cache.key(
                namespace_id=namespace_id,
                user_id=user_id,
                query=query,
                conversation_ids=conversation_ids,
                exclude_conversation_ids=exclude_conversation_ids,
                resource_ids=resource_ids,
                retrieval_signature=getattr(self.vector_db, "retrieval_signature", ""),
            )
            async with self.cache.lock_for(key):
                cached = self.cache.get(key)
                entry = cached or FilteredSearchCacheEntry()
                budget = self.relevance_config.search_timeout_sec
                if timeout_ms is not None:
                    budget = min(budget, timeout_ms / 1000)
                deadline = time.monotonic() + budget
                raw_windows_fetched = 0
                raw_records_scanned = 0
                pending_dropped = 0
                budget_exhausted = False
                raw_scan_capped = False
                stopped_by_client = False
                judged_this_request: set[str] = set()
                window_resource_ids: set[str] = {
                    resource_id
                    for record in entry.raw_records[: entry.raw_cursor]
                    if (resource_id := _resource_id(record)) is not None
                }
                try:
                    while (
                        entry.pending_records
                        and len(entry.filtered_records) < offset + limit
                    ):
                        if time.monotonic() >= deadline:
                            budget_exhausted = True
                            break
                        if await _stop_requested(should_stop):
                            stopped_by_client = True
                            break
                        slice_records: list[IndexRecord] = []
                        for record in entry.pending_records:
                            resource_id = _resource_id(record)
                            if (
                                resource_id is None
                                or resource_id in judged_this_request
                            ):
                                continue
                            slice_records.append(record)
                            if len(slice_records) >= RELEVANCE_SLICE_SIZE:
                                break
                        if not slice_records:
                            break
                        judged_this_request.update(
                            resource_id
                            for record in slice_records
                            if (resource_id := _resource_id(record)) is not None
                        )
                        result = await self.relevance_checker.filter_search_results(
                            query,
                            slice_records,
                            deadline=deadline,
                            index_offset=entry.judged_chunk_count,
                        )
                        entry.judged_chunk_count += len(slice_records)
                        pending_dropped += self._refill_from_pending(
                            entry, slice_records, result
                        )

                    while len(entry.filtered_records) < offset + limit and (
                        entry.raw_cursor < len(entry.raw_records) or entry.has_more_raw
                    ):
                        if time.monotonic() >= deadline:
                            budget_exhausted = True
                            break
                        if raw_records_scanned >= MAX_RAW_RECORDS_PER_REQUEST:
                            raw_scan_capped = True
                            break
                        if await _stop_requested(should_stop):
                            stopped_by_client = True
                            break
                        if entry.raw_cursor >= len(entry.raw_records):
                            if not entry.has_more_raw:
                                break
                            window_offset = (
                                0
                                if entry.raw_pages_scanned_total == 0
                                else entry.raw_window_start + len(entry.raw_records)
                            )
                            page = await self.vector_db.search_page(
                                conversation_ids=conversation_ids,
                                exclude_conversation_ids=exclude_conversation_ids,
                                query=query,
                                namespace_id=namespace_id,
                                user_id=user_id,
                                record_type=IndexRecordType.chunk,
                                offset=window_offset,
                                limit=RAW_WINDOW_SIZE,
                                resource_ids=resource_ids,
                            )
                            raw_records = page.records
                            entry.raw_window_start = window_offset
                            entry.raw_cursor = 0
                            entry.raw_records = raw_records
                            entry.raw_pages_scanned_total += 1
                            raw_windows_fetched += 1
                            entry.has_more_raw = page.has_more
                            window_resource_ids = set()
                            continue

                        slice_size = min(
                            RELEVANCE_SLICE_SIZE,
                            MAX_RAW_RECORDS_PER_REQUEST - raw_records_scanned,
                        )
                        slice_records = entry.raw_records[
                            entry.raw_cursor : entry.raw_cursor + slice_size
                        ]
                        candidates: list[IndexRecord] = []
                        for record in slice_records:
                            resource_id = _resource_id(record)
                            if (
                                resource_id is None
                                or resource_id in entry.seen_resource_ids
                                or resource_id in entry.pending_resource_ids
                                or resource_id in window_resource_ids
                            ):
                                continue
                            window_resource_ids.add(resource_id)
                            candidates.append(record)
                        if not candidates:
                            entry.raw_cursor += len(slice_records)
                            raw_records_scanned += len(slice_records)
                            continue
                        result = await self.relevance_checker.filter_search_results(
                            query,
                            candidates,
                            deadline=deadline,
                            index_offset=entry.judged_chunk_count,
                        )
                        entry.judged_chunk_count += len(candidates)
                        pending_dropped += self._apply_raw_result(
                            entry, candidates, result
                        )
                        entry.raw_cursor += len(slice_records)
                        raw_records_scanned += len(slice_records)
                finally:
                    self.cache.put(key, entry)

            records = entry.filtered_records[offset : offset + limit]
            raw_more = entry.raw_cursor < len(entry.raw_records) or entry.has_more_raw
            has_more = (
                bool(entry.pending_records)
                or raw_more
                or offset + len(records) < len(entry.filtered_records)
            )
            total = None if has_more else len(entry.filtered_records)

            span.set_attribute("search.raw_pages_scanned", raw_windows_fetched)
            span.set_attribute(
                "search.raw_pages_scanned_total", entry.raw_pages_scanned_total
            )
            span.set_attribute("search.raw_windows_fetched", raw_windows_fetched)
            span.set_attribute("search.raw_records_scanned", raw_records_scanned)
            span.set_attribute("search.pending_count", len(entry.pending_records))
            span.set_attribute("search.pending_dropped", pending_dropped)
            span.set_attribute("search.confirmed_count", len(entry.filtered_records))
            if total is not None:
                span.set_attribute("search.filtered_total", total)
            span.set_attribute("search.has_more", has_more)
            span.set_attribute("search.cache_hit", cached is not None)
            span.set_attribute("search.budget_exhausted", budget_exhausted)
            span.set_attribute("search.raw_scan_capped", raw_scan_capped)
            span.set_attribute("search.stopped_by_client", stopped_by_client)
            return SearchPage(records=records, total=total, has_more=has_more)

    def _refill_from_pending(
        self,
        entry: FilteredSearchCacheEntry,
        slice_records: list[IndexRecord],
        result: SearchFilterResult,
    ) -> int:
        input_ids = {
            resource_id
            for record in slice_records
            if (resource_id := _resource_id(record)) is not None
        }
        kept_records = {
            resource_id: record
            for record in result.kept
            if (resource_id := _resource_id(record)) is not None
        }
        pending_records = {
            resource_id: record
            for record in result.pending
            if (resource_id := _resource_id(record)) is not None
        }
        seen_input_ids: set[str] = set()
        remaining_pending: list[IndexRecord] = []
        for record in entry.pending_records:
            resource_id = _resource_id(record)
            if resource_id is None or resource_id not in input_ids:
                remaining_pending.append(record)
                continue
            if resource_id in seen_input_ids:
                continue
            seen_input_ids.add(resource_id)
            if resource_id in kept_records:
                entry.pending_resource_ids.discard(resource_id)
                if resource_id not in entry.seen_resource_ids:
                    entry.seen_resource_ids.add(resource_id)
                    entry.filtered_records.append(kept_records[resource_id])
            elif resource_id in pending_records:
                entry.pending_resource_ids.add(resource_id)
                remaining_pending.append(pending_records[resource_id])
            else:
                entry.pending_resource_ids.discard(resource_id)
        for resource_id, record in pending_records.items():
            if resource_id in input_ids:
                continue
            entry.pending_resource_ids.add(resource_id)
            remaining_pending.append(record)
        entry.pending_records = remaining_pending
        return self._cap_pending(entry)

    def _apply_raw_result(
        self,
        entry: FilteredSearchCacheEntry,
        candidates: list[IndexRecord],
        result: SearchFilterResult,
    ) -> int:
        kept_records = {
            resource_id: record
            for record in result.kept
            if (resource_id := _resource_id(record)) is not None
        }
        pending_records = {
            resource_id: record
            for record in result.pending
            if (resource_id := _resource_id(record)) is not None
        }
        seen_input_ids: set[str] = set()
        for record in candidates:
            resource_id = _resource_id(record)
            if resource_id is None or resource_id in seen_input_ids:
                continue
            seen_input_ids.add(resource_id)
            if resource_id in kept_records:
                entry.pending_resource_ids.discard(resource_id)
                if resource_id not in entry.seen_resource_ids:
                    entry.seen_resource_ids.add(resource_id)
                    entry.filtered_records.append(kept_records[resource_id])
            elif resource_id in pending_records:
                entry.pending_resource_ids.add(resource_id)
                entry.pending_records.append(pending_records[resource_id])
            else:
                entry.pending_resource_ids.discard(resource_id)
        for resource_id, record in pending_records.items():
            if resource_id in seen_input_ids:
                continue
            entry.pending_resource_ids.add(resource_id)
            entry.pending_records.append(record)
        return self._cap_pending(entry)

    def _cap_pending(self, entry: FilteredSearchCacheEntry) -> int:
        overflow = len(entry.pending_records) - self.cache.max_pending_records
        if overflow <= 0:
            return 0
        dropped = entry.pending_records[self.cache.max_pending_records :]
        entry.pending_records = entry.pending_records[: self.cache.max_pending_records]
        for record in dropped:
            resource_id = _resource_id(record)
            if resource_id is not None:
                entry.pending_resource_ids.discard(resource_id)
        return len(dropped)

    async def _paginate_raw(
        self,
        span,
        *,
        query: str,
        namespace_id: str,
        user_id: str | None,
        offset: int,
        limit: int,
        conversation_ids: list[str] | None,
        exclude_conversation_ids: list[str] | None,
        resource_ids: list[str] | None,
    ) -> SearchPage:
        page = await self.vector_db.search_page(
            conversation_ids=conversation_ids,
            exclude_conversation_ids=exclude_conversation_ids,
            query=query,
            namespace_id=namespace_id,
            user_id=user_id,
            record_type=IndexRecordType.chunk,
            offset=offset,
            limit=limit,
            resource_ids=resource_ids,
        )
        records = page.records
        has_more = page.has_more
        span.set_attribute("search.raw_pages_scanned", 1)
        span.set_attribute("search.raw_pages_scanned_total", 0)
        span.set_attribute("search.raw_records_scanned", len(records))
        span.set_attribute("search.has_more", has_more)
        span.set_attribute("search.cache_hit", False)
        span.set_attribute("search.budget_exhausted", False)
        span.set_attribute("search.raw_scan_capped", False)
        return SearchPage(records=records, total=None, has_more=has_more)
