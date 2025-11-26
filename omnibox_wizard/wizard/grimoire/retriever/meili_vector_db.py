from functools import partial
from hashlib import md5
from typing import List, Tuple

from meilisearch_python_sdk import AsyncClient
from meilisearch_python_sdk.errors import MeilisearchApiError
from meilisearch_python_sdk.models.search import Hybrid
from meilisearch_python_sdk.models.settings import (
    Embedders,
    Filter,
    FilterableAttributeFeatures,
    FilterableAttributes,
    UserProvidedEmbedder,
)
from meilisearch_python_sdk.models.task import TaskInfo
from openai import AsyncOpenAI
from opentelemetry import propagate, trace

from common.trace_info import TraceInfo
from omnibox_wizard.wizard.config import VectorConfig
from omnibox_wizard.wizard.grimoire.entity.chunk import Chunk, ResourceChunkRetrieval
from omnibox_wizard.wizard.grimoire.entity.index_record import (
    IndexRecord,
    IndexRecordType,
)
from omnibox_wizard.wizard.grimoire.entity.message import Message
from omnibox_wizard.wizard.grimoire.entity.retrieval import Score
from omnibox_wizard.wizard.grimoire.entity.tools import (
    Condition,
    PrivateSearchResourceType,
    PrivateSearchTool,
    Resource,
)
from omnibox_wizard.wizard.grimoire.retriever.base import BaseRetriever, SearchFunction

tracer = trace.get_tracer(__name__)


def to_filterable_attributes(
    filter_: str, comparison: bool = False
) -> FilterableAttributes:
    """Convert a string filter to FilterableAttributes."""
    return FilterableAttributes(
        attribute_patterns=[filter_],
        features=FilterableAttributeFeatures(
            facet_search=False,
            filter=Filter(equality=True, comparison=comparison),
        ),
    )


def sharded_index_uid(idx: int) -> str:
    return f"omnibox-index-{idx}"


class MeiliVectorDB:
    def __init__(self, config: VectorConfig):
        self.config: VectorConfig = config
        self.batch_size: int = config.batch_size
        self.openai = AsyncOpenAI(
            api_key=config.embedding.api_key, base_url=config.embedding.base_url
        )
        self.meili: AsyncClient = ...
        self.index_uid = "omniboxIndex"
        self.num_shards = 20
        self.embedder_name = "omniboxEmbed"
        self.embedder_dimensions = 1024
        self.has_old_index = False

    async def get_or_init_client(self) -> AsyncClient:
        """Get the initialized MeiliSearch client."""
        if self.meili is ...:
            client = AsyncClient(self.config.host, self.config.meili_api_key)
            try:
                await client.get_index(self.index_uid)
                self.has_old_index = True
            except MeilisearchApiError as e:
                if e.status_code == 404:
                    self.has_old_index = False
                else:
                    raise
            for i in range(self.num_shards):
                await self.init_shard_index(client, sharded_index_uid(i))
            self.meili = client
        return self.meili

    def get_shard(self, namespace_id: str):
        if not namespace_id:
            raise ValueError("namespace_id is required")
        h = md5(namespace_id.encode("utf-8")).digest()
        idx = int.from_bytes(h[:4], byteorder="big")
        idx %= self.num_shards
        return sharded_index_uid(idx)

    async def init_shard_index(self, client: AsyncClient, index_uid: str):
        """Initialize a single shard index with proper settings."""
        index = await client.get_or_create_index(index_uid)

        cur_filters: List[FilterableAttributes] = []
        for f in await index.get_filterable_attributes() or []:
            if isinstance(f, FilterableAttributes):
                cur_filters.append(f)
            elif isinstance(f, str):
                cur_filters.append(to_filterable_attributes(f))
            else:
                raise ValueError(
                    f"Unexpected filterable attribute type: {type(f)}. Expected str or FilterableAttributes."
                )

        expected_filters = [
            "namespace_id",
            "user_id",
            "type",
            "chunk.resource_id",
            "chunk.parent_id",
            "chunk.created_at",
            "chunk.updated_at",
            "message.conversation_id",
        ]
        comparison_filters = [
            "chunk.created_at",
            "chunk.updated_at",
        ]
        missing_filters: List[FilterableAttributes] = []
        for expected_filter in expected_filters:
            found = False
            for cur_filter in cur_filters:
                if expected_filter in cur_filter.attribute_patterns:
                    found = True
                    break
            if not found:
                missing_filters.append(
                    to_filterable_attributes(
                        expected_filter,
                        comparison=expected_filter in comparison_filters,
                    )
                )

        if missing_filters:
            new_filters = cur_filters + missing_filters
            await index.update_filterable_attributes(new_filters)

        embedders = await index.get_embedders()
        if not embedders or self.embedder_name not in embedders.embedders:
            await index.update_embedders(
                Embedders(
                    embedders={
                        self.embedder_name: UserProvidedEmbedder(
                            dimensions=self.embedder_dimensions
                        )
                    }
                )
            )

    @tracer.start_as_current_span("MeiliVectorDB.insert_chunks")
    async def insert_chunks(self, namespace_id: str, chunk_list: List[Chunk]):
        client = await self.get_or_init_client()
        index = client.index(self.get_shard(namespace_id))
        for i in range(0, len(chunk_list), self.batch_size):
            raw_batch = chunk_list[i : i + self.batch_size]

            batch: List[Chunk] = []
            prompts: list[str] = []
            for x in raw_batch:
                prompt: str = x.to_prompt()
                if prompt:
                    batch.append(x)
                    prompts.append(prompt)

            headers = {}
            propagate.inject(headers)

            embeddings = await self.openai.embeddings.create(
                model=self.config.embedding.model, input=prompts, extra_headers=headers
            )
            records = []
            for chunk, embed in zip(batch, embeddings.data):
                record = IndexRecord(
                    id="chunk_{}".format(chunk.chunk_id),
                    type=IndexRecordType.chunk,
                    namespace_id=namespace_id,
                    chunk=chunk,
                    _vectors={
                        self.embedder_name: embed.embedding,
                    },
                )
                records.append(record.model_dump(by_alias=True))
            await index.add_documents(records, primary_key="id")

    @tracer.start_as_current_span("MeiliVectorDB.upsert_message")
    async def upsert_message(self, namespace_id: str, user_id: str, message: Message):
        client = await self.get_or_init_client()
        index = client.index(self.get_shard(namespace_id))
        record_id = "message_{}".format(message.message_id)

        if not message.message.content.strip():
            await index.delete_document(record_id)
            return

        headers = {}
        propagate.inject(headers)

        embedding = await self.openai.embeddings.create(
            model=self.config.embedding.model,
            input=message.message.content or "",
            extra_headers=headers,
        )
        record = IndexRecord(
            id=record_id,
            type=IndexRecordType.message,
            namespace_id=namespace_id,
            user_id=user_id,
            message=message,
            _vectors={
                self.embedder_name: embedding.data[0].embedding,
            },
        )
        await index.add_documents([record.model_dump(by_alias=True)], primary_key="id")

    @tracer.start_as_current_span("MeiliVectorDB.remove_conversation")
    async def remove_conversation(self, namespace_id: str, conversation_id: str):
        await self.delete_from_both_indexes(
            namespace_id,
            filter_=[
                "type = {}".format(IndexRecordType.message.value),
                "namespace_id = {}".format(namespace_id),
                "message.conversation_id = {}".format(conversation_id),
            ],
        )

    @tracer.start_as_current_span("MeiliVectorDB.remove_chunks")
    async def remove_chunks(self, namespace_id: str, resource_id: str):
        await self.delete_from_both_indexes(
            namespace_id,
            filter_=[
                "type = {}".format(IndexRecordType.chunk.value),
                "namespace_id = {}".format(namespace_id),
                "chunk.resource_id = {}".format(resource_id),
            ],
        )

    @tracer.start_as_current_span("MeiliVectorDB.vector_params")
    async def vector_params(self, query: str) -> dict:
        if query:
            headers = {}
            propagate.inject(headers)

            embedding = await self.openai.embeddings.create(
                model=self.config.embedding.model, input=query, extra_headers=headers
            )
            vector = embedding.data[0].embedding
            hybrid = Hybrid(embedder=self.embedder_name, semantic_ratio=0.5)
            return {
                "vector": vector,
                "hybrid": hybrid,
            }
        return {}

    @tracer.start_as_current_span("MeiliVectorDB.query_both_indexes")
    async def query_both_indexes(
        self,
        namespace_id: str,
        query: str,
        filter_: List[str | List[str]],
        limit: int,
        vector_params: dict,
        **search_kwargs,
    ) -> List[dict]:
        client = await self.get_or_init_client()

        hits = []
        if self.has_old_index:
            old_index = client.index(self.index_uid)
            result = await old_index.search(
                query,
                filter=filter_,
                limit=limit,
                **vector_params,
                **search_kwargs,
                show_ranking_score=True,
            )
            hits.extend(result.hits)

        index = client.index(self.get_shard(namespace_id))
        result = await index.search(
            query,
            filter=filter_,
            limit=limit,
            **vector_params,
            **search_kwargs,
            show_ranking_score=True,
        )
        hits.extend(result.hits)

        hits.sort(key=lambda x: x.get("_rankingScore", 0), reverse=True)
        return hits[:limit]

    @tracer.start_as_current_span("MeiliVectorDB.delete_from_both_indexes")
    async def delete_from_both_indexes(
        self,
        namespace_id: str,
        filter_: List[str | List[str]],
    ):
        client = await self.get_or_init_client()

        tasks: List[TaskInfo] = []
        if self.has_old_index:
            old_index = client.index(self.index_uid)
            tasks.append(await old_index.delete_documents_by_filter(filter=filter_))

        index = client.index(self.get_shard(namespace_id))
        tasks.append(await index.delete_documents_by_filter(filter=filter_))

        for task in tasks:
            await client.wait_for_task(task.task_uid)

    @tracer.start_as_current_span("MeiliVectorDB.search")
    async def search(
        self,
        query: str,
        namespace_id: str,
        user_id: str | None,
        record_type: IndexRecordType | None,
        offset: int,
        limit: int,
    ) -> List[IndexRecord]:
        filter_: List[str | List[str]] = []
        filter_.append("namespace_id = {}".format(namespace_id))
        if user_id:
            filter_.append(
                "user_id NOT EXISTS OR user_id IS NULL OR user_id = {}".format(user_id)
            )
        if record_type:
            filter_.append("type = {}".format(record_type.value))
        vector_params: dict = await self.vector_params(query)

        hits = await self.query_both_indexes(
            namespace_id,
            query,
            filter_,
            offset + limit,
            vector_params,
        )
        return [IndexRecord(**hit) for hit in hits[offset:]]

    @tracer.start_as_current_span("MeiliVectorDB.query_chunks")
    async def query_chunks(
        self,
        namespace_id: str,
        query: str,
        k: int,
        filter_: List[str | List[str]],
    ) -> List[Tuple[Chunk, float]]:
        combined_filters = filter_ + ["type = {}".format(IndexRecordType.chunk.value)]
        vector_params: dict = await self.vector_params(query)
        hits = await self.query_both_indexes(
            namespace_id,
            query,
            combined_filters,
            k * 2,
            vector_params,
        )
        output: List[Tuple[Chunk, float]] = []
        for hit in hits:
            chunk_data = hit["chunk"]
            score = hit["_rankingScore"]
            if chunk_data:
                chunk = Chunk(**chunk_data)
                output.append((chunk, score))
        return output


class MeiliVectorRetriever(BaseRetriever):
    def __init__(self, config: VectorConfig):
        self.vector_db = MeiliVectorDB(config)

    @staticmethod
    def get_folder(resource_id: str, resources: list[Resource]) -> str | None:
        for resource in resources:
            if (
                resource.type == PrivateSearchResourceType.FOLDER
                and resource_id in resource.child_ids
            ):
                return resource.name
        return None

    @staticmethod
    def get_type(
        resource_id: str, resources: list[Resource]
    ) -> PrivateSearchResourceType | None:
        for resource in resources:
            if resource.id == resource_id:
                return resource.type
        return None

    def get_function(
        self, private_search_tool: PrivateSearchTool, **kwargs
    ) -> SearchFunction:
        return partial(
            self.query, private_search_tool=private_search_tool, k=40, **kwargs
        )

    @classmethod
    def get_schema(cls) -> dict:
        return cls.generate_schema(
            "private_search",
            'Search for user\'s private & personal resources. Return in <cite id=""></cite> format.',
        )

    @tracer.start_as_current_span("MeiliVectorRetriever.query")
    async def query(
        self,
        query: str,
        k: int,
        *,
        private_search_tool: PrivateSearchTool,
        trace_info: TraceInfo | None = None,
    ) -> list[ResourceChunkRetrieval]:
        condition: Condition = private_search_tool.to_condition()
        where = condition.to_meili_where()
        if len(where) == 0:
            trace_info and trace_info.warning(
                {
                    "warning": "empty_where",
                    "where": where,
                    "condition": condition.model_dump() if condition else condition,
                }
            )
            return []

        recall_result_list = await self.vector_db.query_chunks(
            private_search_tool.namespace_id, query, k, where
        )
        retrievals: List[ResourceChunkRetrieval] = [
            ResourceChunkRetrieval(
                chunk=chunk,
                folder=self.get_folder(
                    chunk.resource_id, private_search_tool.resources or []
                ),
                type=self.get_type(
                    chunk.resource_id, private_search_tool.visible_resources or []
                ),
                score=Score(recall=score, rerank=0),
            )
            for chunk, score in recall_result_list
        ]
        trace_info and trace_info.debug(
            {
                "where": where,
                "condition": condition.model_dump() if condition else condition,
                "len(retrievals)": len(retrievals),
            }
        )
        return retrievals
