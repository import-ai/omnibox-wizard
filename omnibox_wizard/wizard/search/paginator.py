import asyncio
import time
from dataclasses import dataclass, field

from opentelemetry import trace

from wizard_common.grimoire.config import RelevanceConfig
from wizard_common.grimoire.entity.index_record import IndexRecord, IndexRecordType
from wizard_common.grimoire.retriever.relevance import RelevanceChecker
from wizard_common.grimoire.retriever.weaviate_vector_db import WeaviateVectorDB

tracer = trace.get_tracer(__name__)

RAW_PAGE_SIZE = 20
MAX_RAW_PAGES_PER_REQUEST = 10
CACHE_TTL_SECONDS = 30.0
CACHE_MAX_ENTRIES = 100
CACHE_MAX_FILTERED_RECORDS = 500

SearchKey = tuple[str, str, str, str, tuple[str, ...], tuple[str, ...], tuple[str, ...]]


@dataclass
class SearchPage:
    records: list[IndexRecord]
    total: int | None
    has_more: bool


@dataclass
class FilteredSearchCacheEntry:
    filtered_records: list[IndexRecord] = field(default_factory=list)
    next_raw_offset: int = 0
    has_more_raw: bool = True
    seen_resource_ids: set[str] = field(default_factory=set)
    judged_chunk_count: int = 0
    expires_at: float = 0.0
    raw_pages_scanned_total: int = 0


def _chunk_records(records: list[IndexRecord]) -> list[IndexRecord]:
    return [
        record
        for record in records
        if record.type == IndexRecordType.chunk and record.chunk is not None
    ]


class FilteredSearchCache:
    def __init__(
        self,
        ttl_seconds: float = CACHE_TTL_SECONDS,
        max_entries: int = CACHE_MAX_ENTRIES,
        max_filtered_records: int = CACHE_MAX_FILTERED_RECORDS,
    ):
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self.max_filtered_records = max_filtered_records
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
    ) -> SearchKey:
        return (
            namespace_id,
            user_id or "",
            query,
            IndexRecordType.chunk.value,
            tuple(conversation_ids or ()),
            tuple(exclude_conversation_ids or ()),
            tuple(sorted(resource_ids or ())),
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
            )
            async with self.cache.lock_for(key):
                cached = self.cache.get(key)
                entry = cached or FilteredSearchCacheEntry()
                deadline = time.monotonic() + self.relevance_config.search_timeout_sec
                pages_this_request = 0
                raw_records_scanned = 0
                budget_exhausted = False
                try:
                    while (
                        len(entry.filtered_records) < offset + limit
                        and entry.has_more_raw
                    ):
                        if time.monotonic() >= deadline:
                            budget_exhausted = True
                            break
                        if pages_this_request >= MAX_RAW_PAGES_PER_REQUEST:
                            budget_exhausted = True
                            break
                        raw_records = await self.vector_db.search(
                            conversation_ids=conversation_ids,
                            exclude_conversation_ids=exclude_conversation_ids,
                            query=query,
                            namespace_id=namespace_id,
                            user_id=user_id,
                            record_type=IndexRecordType.chunk,
                            offset=entry.next_raw_offset,
                            limit=RAW_PAGE_SIZE,
                            resource_ids=resource_ids,
                        )
                        entry.next_raw_offset += RAW_PAGE_SIZE
                        entry.raw_pages_scanned_total += 1
                        pages_this_request += 1
                        chunk_records = _chunk_records(raw_records)
                        raw_records_scanned += len(chunk_records)
                        entry.has_more_raw = len(chunk_records) >= RAW_PAGE_SIZE
                        kept = await self.relevance_checker.filter_search_results(
                            query,
                            raw_records,
                            deadline=deadline,
                            index_offset=entry.judged_chunk_count,
                        )
                        entry.judged_chunk_count += len(chunk_records)
                        for record in kept:
                            if (
                                record.type != IndexRecordType.chunk
                                or record.chunk is None
                            ):
                                continue
                            if record.chunk.resource_id in entry.seen_resource_ids:
                                continue
                            entry.seen_resource_ids.add(record.chunk.resource_id)
                            entry.filtered_records.append(record)
                finally:
                    self.cache.put(key, entry)

            records = entry.filtered_records[offset : offset + limit]
            if entry.has_more_raw:
                total = None
                has_more = True
            else:
                total = len(entry.filtered_records)
                has_more = False

            span.set_attribute("search.raw_pages_scanned", pages_this_request)
            span.set_attribute(
                "search.raw_pages_scanned_total", entry.raw_pages_scanned_total
            )
            span.set_attribute("search.raw_records_scanned", raw_records_scanned)
            if total is not None:
                span.set_attribute("search.filtered_total", total)
            span.set_attribute("search.has_more", has_more)
            span.set_attribute("search.cache_hit", cached is not None)
            span.set_attribute("search.budget_exhausted", budget_exhausted)
            return SearchPage(records=records, total=total, has_more=has_more)

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
        records = await self.vector_db.search(
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
        has_more = len(records) >= limit
        span.set_attribute("search.raw_pages_scanned", 1)
        span.set_attribute("search.raw_pages_scanned_total", 0)
        span.set_attribute("search.raw_records_scanned", len(records))
        span.set_attribute("search.has_more", has_more)
        span.set_attribute("search.cache_hit", False)
        span.set_attribute("search.budget_exhausted", False)
        return SearchPage(records=records, total=None, has_more=has_more)
