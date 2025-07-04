from functools import partial
from typing import List, Tuple

from meilisearch_python_sdk import AsyncClient
from meilisearch_python_sdk.models.search import Hybrid
from meilisearch_python_sdk.models.settings import (
    Embedders,
    FilterableAttributeFeatures,
    FilterableAttributes,
    Filter,
    UserProvidedEmbedder,
)
from openai import AsyncOpenAI

from omnibox.common.trace_info import TraceInfo
from omnibox.wizard.config import VectorConfig
from omnibox.wizard.grimoire.entity.chunk import Chunk, ResourceChunkRetrieval
from omnibox.wizard.grimoire.entity.index_record import IndexRecord, IndexRecordType
from omnibox.wizard.grimoire.entity.message import Message
from omnibox.wizard.grimoire.entity.retrieval import Score
from omnibox.wizard.grimoire.entity.tools import (
    Condition,
    PrivateSearchResourceType,
    PrivateSearchTool,
    Resource,
)
from omnibox.wizard.grimoire.retriever.base import BaseRetriever, SearchFunction


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


class MeiliVectorDB:
    def __init__(self, config: VectorConfig):
        self.config: VectorConfig = config
        self.batch_size: int = config.batch_size
        self.openai = AsyncOpenAI(
            api_key=config.embedding.api_key, base_url=config.embedding.base_url
        )
        self.meili: AsyncClient = ...
        self.index_uid = "omniboxIndex"
        self.embedder_name = "omniboxEmbed"
        self.embedder_dimensions = 1024

    async def get_index(self):
        if self.meili is ...:
            self.meili = AsyncClient(self.config.host, self.config.meili_api_key)
            await self.init_index()
        return self.meili.index(self.index_uid)

    async def init_index(self):
        index = await self.meili.get_or_create_index(self.index_uid)

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

    async def insert_chunks(self, namespace_id: str, chunk_list: List[Chunk]):
        index = await self.get_index()
        for i in range(0, len(chunk_list), self.batch_size):
            batch = chunk_list[i: i + self.batch_size]
            embeddings = await self.openai.embeddings.create(
                model=self.config.embedding.model,
                input=[chunk.text or "" for chunk in batch],
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

    async def upsert_message(self, namespace_id: str, user_id: str, message: Message):
        index = await self.get_index()
        record_id = "message_{}".format(message.message_id)

        if not message.message.content.strip():
            await index.delete_document(record_id)
            return

        embedding = await self.openai.embeddings.create(
            model=self.config.embedding.model,
            input=message.message.content or "",
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

    async def remove_chunks(self, namespace_id: str, resource_id: str):
        index = await self.get_index()
        await index.delete_documents_by_filter(
            filter=[
                "type = {}".format(IndexRecordType.chunk.value),
                "namespace_id = {}".format(namespace_id),
                "chunk.resource_id = {}".format(resource_id),
            ]
        )

    async def vector_params(self, query: str) -> dict:
        if query:
            embedding = await self.openai.embeddings.create(
                model=self.config.embedding.model, input=query
            )
            vector = embedding.data[0].embedding
            hybrid = Hybrid(embedder=self.embedder_name, semantic_ratio=0.5)
            return {
                "vector": vector,
                "hybrid": hybrid,
            }
        return {}

    async def search(
            self,
            query: str,
            namespace_id: str | None,
            user_id: str | None,
            record_type: IndexRecordType | None,
            offset: int,
            limit: int,
    ) -> List[IndexRecord]:
        filter_: List[str | List[str]] = []
        if namespace_id:
            filter_.append("namespace_id = {}".format(namespace_id))
        if user_id:
            filter_.append("user_id NOT EXISTS OR user_id IS NULL OR user_id = {}".format(user_id))
        if record_type:
            filter_.append("type = {}".format(record_type.value))
        vector_params: dict = await self.vector_params(query)
        index = await self.get_index()
        results = await index.search(query, filter=filter_, offset=offset, limit=limit, **vector_params)
        return [IndexRecord(**hit) for hit in results.hits]

    async def query_chunks(
            self,
            query: str,
            k: int,
            filter_: List[str | List[str]],
    ) -> List[Tuple[Chunk, float]]:
        index = await self.get_index()
        combined_filters = filter_ + ["type = {}".format(IndexRecordType.chunk.value)]
        vector_params: dict = await self.vector_params(query)
        results = await index.search(query, limit=k, filter=combined_filters, show_ranking_score=True, **vector_params)
        output: List[Tuple[Chunk, float]] = []
        for hit in results.hits:
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
    def get_type(resource_id: str, resources: list[Resource]) -> PrivateSearchResourceType | None:
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
            "Search for user's private & personal resources. Return in <cite id=\"\"></cite> format."
        )

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
            trace_info and trace_info.warning({
                "warning": "empty_where",
                "where": where,
                "condition": condition.model_dump() if condition else condition,
            })
            return []

        recall_result_list = await self.vector_db.query_chunks(query, k, where)
        retrievals: List[ResourceChunkRetrieval] = [
            ResourceChunkRetrieval(
                chunk=chunk,
                folder=self.get_folder(chunk.resource_id, private_search_tool.resources or []),
                type=self.get_type(chunk.resource_id, private_search_tool.visible_resources or []),
                score=Score(recall=score, rerank=0),
            )
            for chunk, score in recall_result_list
        ]
        trace_info and trace_info.debug({
            "where": where,
            "condition": condition.model_dump() if condition else condition,
            "len(retrievals)": len(retrievals),
        })
        return retrievals
