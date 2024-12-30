import asyncio
from concurrent.futures.thread import ThreadPoolExecutor
from typing import List, Tuple

import chromadb
from chromadb.utils.embedding_functions.openai_embedding_function import OpenAIEmbeddingFunction

from common.trace_info import TraceInfo
from wizard.config import VectorConfig
from wizard.grimoire.entity.api import Condition
from wizard.grimoire.entity.chunk import Chunk


class VectorDB:
    def __init__(self, config: VectorConfig):
        client: chromadb.ClientAPI = chromadb.HttpClient(host=config.host, port=config.port)
        embed_func = OpenAIEmbeddingFunction(
            api_base=config.embedding.base_url,
            api_key=config.embedding.api_key,
            model_name=config.embedding.model
        )
        collection: chromadb.Collection = client.get_or_create_collection(
            name="default", metadata={"hnsw:space": "ip"}, embedding_function=embed_func)

        self.client: chromadb.ClientAPI = client
        self.collection: chromadb.Collection = collection
        self.batch_size: int = config.batch_size

    def insert(self, chunk_list: List[Chunk]):
        for i in range(0, len(chunk_list), self.batch_size):
            batch: List[Chunk] = chunk_list[i:i + self.batch_size]
            self.collection.add(
                documents=[c.text for c in batch],
                ids=[c.chunk_id for c in batch],
                metadatas=[c.metadata for c in batch]
            )

    def remove(self, namespace_id: str, resource_id: str):
        self.collection.delete(where={"$and": [{"namespace_id": namespace_id}, {"resource_id": resource_id}]})

    def query(
            self,
            query: str,
            k: int,
            *,
            condition: dict | Condition = None,
            trace_info: TraceInfo
    ) -> List[Tuple[Chunk, float]]:
        if isinstance(condition, dict):
            condition = Condition(**condition)
        and_clause = [{"namespace_id": condition.namespace_id}]

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
        where = {"$and": and_clause} if len(and_clause) > 1 else and_clause[0]
        trace_info.debug({"where": where, "condition": condition.model_dump()})

        batch_result_list: chromadb.QueryResult = self.collection.query(
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


class AsyncVectorDB(VectorDB):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.executor = ThreadPoolExecutor()

    async def insert(self, *args, **kwargs):
        loop = asyncio.get_event_loop()

        def func(_args, _kwargs):
            return super(AsyncVectorDB, self).insert(*_args, **_kwargs)

        return await loop.run_in_executor(self.executor, func, args, kwargs)

    async def remove(self, *args, **kwargs):
        loop = asyncio.get_event_loop()

        def func(_args, _kwargs):
            return super(AsyncVectorDB, self).remove(*_args, **_kwargs)

        return await loop.run_in_executor(self.executor, func, args, kwargs)

    async def query(self, *args, **kwargs) -> List[Tuple[Chunk, float]]:
        loop = asyncio.get_event_loop()

        def func(_args, _kwargs):
            return super(AsyncVectorDB, self).query(*_args, **_kwargs)

        return await loop.run_in_executor(self.executor, func, args, kwargs)


__all__ = ["VectorDB", "AsyncVectorDB"]
