from functools import partial
from typing import List, Tuple

from meilisearch_python_sdk import AsyncClient
from openai import AsyncOpenAI

from common.trace_info import TraceInfo
from wizard.config import VectorConfig
from wizard.grimoire.entity.chunk import Chunk, ResourceChunkRetrieval
from wizard.grimoire.entity.index_record import IndexRecord, IndexRecordType
from wizard.grimoire.entity.retrieval import Score
from wizard.grimoire.entity.tools import (
    Condition,
    PrivateSearchResourceType,
    PrivateSearchTool,
    Resource,
)
from wizard.grimoire.retriever.base import BaseRetriever, SearchFunction


class MeiliVectorDB:
    def __init__(self, config: VectorConfig):
        self.config: VectorConfig = config
        self.batch_size: int = config.batch_size
        self.openai = AsyncOpenAI(
            api_key=config.embedding.api_key, base_url=config.embedding.base_url
        )
        self.meili = AsyncClient(config.host, config.meili_api_key)
        self.index = self.meili.index("omnibox_index")

    async def insert(self, namespace_id: str, chunk_list: List[Chunk]):
        for i in range(0, len(chunk_list), self.batch_size):
            batch = chunk_list[i : i + self.batch_size]
            embeddings = await self.openai.embeddings.create(
                model=self.config.embedding.model,
                input=[chunk.text or "" for chunk in batch],
            )
            records = []
            for chunk, embed in zip(batch, embeddings.data):
                record = IndexRecord(
                    id=chunk.chunk_id,
                    type=IndexRecordType.chunk,
                    namespace_id=namespace_id,
                    chunk=chunk,
                    _vectors={
                        "omnibox_embed": embed.embedding,
                    },
                )
                records.append(record.model_dump(by_alias=True))
            await self.index.add_documents([record.model_dump() for record in records])

    async def remove(self, namespace_id: str, resource_id: str):
        await self.index.delete_documents_by_filter(
            filter=[
                "type = {}".format(IndexRecordType.chunk),
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
        type_filter = "type = {}".format(IndexRecordType.chunk)
        results = await self.index.search(
            query, limit=k, filter=filter + [type_filter], show_ranking_score=True
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
