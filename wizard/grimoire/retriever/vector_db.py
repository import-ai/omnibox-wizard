import asyncio
from asyncio import Task
from functools import partial
from typing import List, Tuple

import chromadb
from chromadb.utils.embedding_functions.openai_embedding_function import OpenAIEmbeddingFunction

from common.trace_info import TraceInfo
from wizard.config import VectorConfig
from wizard.grimoire.entity.chunk import Chunk, ResourceChunkRetrieval
from wizard.grimoire.entity.retrieval import Score
from wizard.grimoire.entity.tools import Condition, PrivateSearchTool, Resource, ResourceType
from wizard.grimoire.retriever.base import BaseRetriever, SearchFunction

AsyncCollection = chromadb.api.async_api.AsyncCollection


class VectorDB:
    def __init__(self, config: VectorConfig):
        self.config: VectorConfig = config
        self.client: Task[chromadb.AsyncClientAPI] = asyncio.create_task(
            chromadb.AsyncHttpClient(host=self.config.host, port=self.config.port)
        )
        self.embed_func: OpenAIEmbeddingFunction = OpenAIEmbeddingFunction(
            api_base=self.config.embedding.base_url,
            api_key=self.config.embedding.api_key,
            model_name=self.config.embedding.model
        )
        self.batch_size: int = config.batch_size

    async def get_collection(self, name: str) -> AsyncCollection:
        client: chromadb.AsyncClientAPI = await self.client
        collection: AsyncCollection = await client.get_or_create_collection(
            name=name, metadata={"hnsw:space": "ip"}, embedding_function=self.embed_func)
        return collection

    async def insert(self, namespace_id: str, chunk_list: List[Chunk]):
        collection: AsyncCollection = await self.get_collection(name=namespace_id)
        for i in range(0, len(chunk_list), self.batch_size):
            batch: List[Chunk] = chunk_list[i:i + self.batch_size]
            await collection.add(
                documents=[c.text for c in batch],
                ids=[c.chunk_id for c in batch],
                metadatas=[c.metadata for c in batch]
            )

    async def remove(self, namespace_id: str, resource_id: str):
        collection: AsyncCollection = await self.get_collection(name=namespace_id)
        return await collection.delete(where={"resource_id": resource_id})

    async def query(
            self,
            query: str,
            k: int,
            namespace_id: str,
            where: dict
    ) -> List[Tuple[Chunk, float]]:
        collection = await self.get_collection(name=namespace_id)
        batch_result_list: chromadb.QueryResult = await collection.query(
            query_texts=[query], n_results=k, where=where)
        result_list: List[Tuple[Chunk, float]] = []
        for chunk_id, document, metadata, distance in zip(
                batch_result_list["ids"][0],
                batch_result_list["documents"][0],
                batch_result_list["metadatas"][0],
                batch_result_list["distances"][0],
        ):
            result_list.append((Chunk(chunk_id=chunk_id, text=document, **metadata), distance))
        return result_list


class VectorRetriever(BaseRetriever):

    def __init__(self, config: VectorConfig):
        self.vector_db: VectorDB = VectorDB(config)

    @classmethod
    def get_folder(cls, resource_id: str, resources: list[Resource]) -> str | None:
        for resource in resources:
            if resource.resource_type == ResourceType.FOLDER and resource_id in resource.sub_resource_ids:
                return resource.name
        return None

    def get_function(self, private_search_tool: PrivateSearchTool, **kwargs) -> SearchFunction:
        return partial(self.query, private_search_tool=private_search_tool, k=20, **kwargs)

    def get_schema(self) -> dict:
        return self.generate_schema("private_search", "Search for user's private & personal resources.")

    async def query(
            self,
            query: str,
            k: int,
            *,
            private_search_tool: PrivateSearchTool,
            trace_info: TraceInfo | None = None
    ) -> list[ResourceChunkRetrieval]:
        condition: Condition = private_search_tool.to_condition()
        where = condition.to_chromadb_where()
        if trace_info:
            trace_info.debug({"where": where, "condition": condition.model_dump() if condition else condition})
        if not where:
            return []

        recall_result_list: List[Tuple[Chunk, float]] = await self.vector_db.query(
            query, k, condition.namespace_id, where
        )
        retrievals: List[ResourceChunkRetrieval] = [
            ResourceChunkRetrieval(
                chunk=chunk,
                folder=self.get_folder(chunk.resource_id, private_search_tool.resources or []),
                score=Score(recall=score, rerank=0)
            ) for chunk, score in recall_result_list
        ]
        return retrievals


__all__ = ["VectorDB", "VectorRetriever"]
