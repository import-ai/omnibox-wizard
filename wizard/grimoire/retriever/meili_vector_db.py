from functools import partial
from typing import List, Tuple

from meilisearch_python_sdk import AsyncClient
from meilisearch_python_sdk.models.settings import (
    Embedders,
    FilterableAttributeFeatures,
    FilterableAttributes,
    Filter,
    UserProvidedEmbedder,
)
from openai import AsyncOpenAI

from common.trace_info import TraceInfo
from wizard.config import VectorConfig
from wizard.grimoire.entity.chunk import Chunk, ResourceChunkRetrieval
from wizard.grimoire.entity.index_record import IndexRecord, IndexRecordType
from wizard.grimoire.entity.message import Message
from wizard.grimoire.entity.retrieval import Score
from wizard.grimoire.entity.tools import (
    Condition,
    PrivateSearchResourceType,
    PrivateSearchTool,
    Resource,
)
from wizard.grimoire.retriever.base import BaseRetriever, SearchFunction


def to_filterable_attributes(
    filter: str, comparison: bool = False
) -> FilterableAttributes:
    """Convert a string filter to FilterableAttributes."""
    return FilterableAttributes(
        attribute_patterns=[filter],
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
        self.meili = AsyncClient(config.host, config.meili_api_key)
        self.index_uid = "omniboxIndex"
        self.embedder_name = "omniboxEmbed"
        self.embedder_dimensions = 1024

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
        index = self.meili.index(self.index_uid)
        for i in range(0, len(chunk_list), self.batch_size):
            batch = chunk_list[i : i + self.batch_size]
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
        embedding = await self.openai.embeddings.create(
            model=self.config.embedding.model,
            input=message.message.content or "",
        )
        record = IndexRecord(
            id="message_{}".format(message.message_id),
            type=IndexRecordType.message,
            namespace_id=namespace_id,
            user_id=user_id,
            message=message,
            _vectors={
                self.embedder_name: embedding.data[0].embedding,
            },
        )
        index = self.meili.index(self.index_uid)
        await index.add_documents([record.model_dump(by_alias=True)], primary_key="id")

    async def remove_chunks(self, namespace_id: str, resource_id: str):
        index = self.meili.index(self.index_uid)
        await index.delete_documents_by_filter(
            filter=[
                "type = {}".format(IndexRecordType.chunk.value),
                "namespace_id = {}".format(namespace_id),
                "chunk.resource_id = {}".format(resource_id),
            ]
        )

    async def query_chunks(
        self,
        query: str,
        k: int,
        filter: List[str | List[str]],
    ) -> List[Tuple[Chunk, float]]:
        index = self.meili.index(self.index_uid)
        combined_filters = filter + ["type = {}".format(IndexRecordType.chunk.value)]
        results = await index.search(
            query, limit=k, filter=combined_filters, show_ranking_score=True
        )
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

    @classmethod
    def get_folder(cls, resource_id: str, resources: list[Resource]) -> str | None:
        for resource in resources:
            if (
                resource.type == PrivateSearchResourceType.FOLDER
                and resource_id in resource.child_ids
            ):
                return resource.name
        return None

    def get_function(
        self, private_search_tool: PrivateSearchTool, **kwargs
    ) -> SearchFunction:
        return partial(
            self.query, private_search_tool=private_search_tool, k=20, **kwargs
        )

    def get_schema(self) -> dict:
        return self.generate_schema(
            "private_search", "Search for user's private & personal resources."
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
        if trace_info:
            trace_info.debug(
                {
                    "where": where,
                    "condition": condition.model_dump() if condition else condition,
                }
            )
        if len(where) == 0:
            return []

        recall_result_list = await self.vector_db.query_chunks(query, k, where)
        retrievals: List[ResourceChunkRetrieval] = [
            ResourceChunkRetrieval(
                chunk=chunk,
                folder=self.get_folder(
                    chunk.resource_id, private_search_tool.resources or []
                ),
                score=Score(recall=score, rerank=0),
            )
            for chunk, score in recall_result_list
        ]
        return retrievals


async def init_meili_vector_db(config: VectorConfig):
    vector_db = MeiliVectorDB(config)
    await vector_db.init_index()
    return vector_db
