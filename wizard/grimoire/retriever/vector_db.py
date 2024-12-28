from typing import List, Tuple

import chromadb
from chromadb.api.models.AsyncCollection import AsyncCollection
from chromadb.utils.embedding_functions.openai_embedding_function import OpenAIEmbeddingFunction

from wizard.config import VectorConfig
from wizard.grimoire.entity.chunk import Chunk


class VectorDB:
    def __init__(self, client: chromadb.AsyncClientAPI, collection: AsyncCollection, batch_size: int = 1):
        self.client: chromadb.AsyncClientAPI = client
        self.collection: AsyncCollection = collection
        self.batch_size: int = batch_size

    @classmethod
    async def from_config(cls, config: VectorConfig) -> "VectorDB":
        client: chromadb.AsyncClientAPI = await chromadb.AsyncHttpClient(host=config.host, port=config.port)
        embed_func = OpenAIEmbeddingFunction(
            api_base=config.embedding.base_url,
            api_key=config.embedding.api_key,
            model_name=config.embedding.model
        )
        collection: AsyncCollection = await client.get_or_create_collection(
            name="default", metadata={"hnsw:space": "ip"}, embedding_function=embed_func)
        return cls(client, collection, config.batch_size)

    async def insert(self, chunk_list: List[Chunk]):
        for i in range(0, len(chunk_list), self.batch_size):
            batch: List[Chunk] = chunk_list[i:i + self.batch_size]
            await self.collection.add(
                documents=[c.text for c in batch],
                ids=[c.chunk_id for c in batch],
                metadatas=[c.metadata for c in batch]
            )

    async def remove(self, namespace: str, element_id: str):
        await self.collection.delete(where={"$and": [{"namespace": namespace}, {"element_id": element_id}]})

    async def query(self, namespace: str, query: str, k: int, element_id_list: List[str] = None) -> List[Tuple[Chunk, float]]:
        where = {"namespace": namespace}
        if element_id_list is not None:
            where = {"$and": [where, {"element_id": {"$in": element_id_list}}]}

        batch_result_list: chromadb.QueryResult = await self.collection.query(
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


__all__ = ["VectorDB"]
