import asyncio
from asyncio import Task
from typing import List, Tuple

import chromadb
from chromadb.utils.embedding_functions.openai_embedding_function import OpenAIEmbeddingFunction

from common.trace_info import TraceInfo
from wizard.config import VectorConfig
from wizard.grimoire.entity.api import Condition
from wizard.grimoire.entity.chunk import Chunk, TextRetrieval
from wizard.grimoire.entity.retrieval import Score

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
            *,
            condition: dict | Condition = None,
            trace_info: TraceInfo | None = None
    ) -> List[Tuple[Chunk, float]]:
        if isinstance(condition, dict):
            condition = Condition(**condition)
        and_clause = []

        or_clause = []
        if condition.resource_ids is not None:
            or_clause.append({"resource_id": {"$in": condition.resource_ids}})
        if condition.parent_ids is not None:
            or_clause.append({"parent_id": {"$in": condition.parent_ids}})
        if or_clause:
            and_clause.append({"$or": or_clause} if len(or_clause) > 1 else or_clause[0])

        if condition.created_at is not None:
            and_clause.append({"created_at": {"$gte": condition.created_at[0], "$lte": condition.created_at[1]}})
        if condition.updated_at is not None:
            and_clause.append({"updated_at": {"$gte": condition.updated_at[0], "$lte": condition.updated_at[1]}})
        if and_clause:
            where = {"$and": and_clause} if len(and_clause) > 1 else and_clause[0]
        else:
            where = None
        if trace_info:
            trace_info.debug({"where": where, "condition": condition.model_dump()})

        collection = await self.get_collection(name=condition.namespace_id)
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


class VectorRetriever(VectorDB):

    async def query(
            self,
            query: str,
            k: int,
            *,
            condition: dict | Condition = None,
            trace_info: TraceInfo | None = None
    ) -> list[TextRetrieval]:
        recall_result_list: List[Tuple[Chunk, float]] = await super().query(
            query, k, condition=condition, trace_info=trace_info
        )
        retrievals: List[TextRetrieval] = [
            TextRetrieval(chunk=chunk, score=Score(recall=score, rerank=0))
            for chunk, score in recall_result_list
        ]
        return retrievals


__all__ = ["VectorDB", "VectorRetriever"]
