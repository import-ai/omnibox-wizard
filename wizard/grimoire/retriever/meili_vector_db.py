from typing import List, Tuple

from meilisearch_python_sdk import AsyncClient

from wizard.config import VectorConfig
from wizard.grimoire.entity.chunk import Chunk
from wizard.grimoire.entity.index_record import IndexRecord, IndexRecordType


class MeiliVectorDB:
    def __init__(self, config: VectorConfig):
        self.config: VectorConfig = config
        self.batch_size: int = config.batch_size
        self.meili_client = AsyncClient(
            config.host, config.meili_api_key)
        self.index = self.meili_client.index("omnibox_index")

    async def insert(self, namespace_id: str, chunk_list: List[Chunk]):
        for i in range(0, len(chunk_list), self.batch_size):
            batch = chunk_list[i:i + self.batch_size]
            records = [IndexRecord(
                id=chunk.chunk_id, type=IndexRecordType.chunk, chunk=chunk) for chunk in batch]
            await self.index.add_documents([record.model_dump()
                                     for record in records])

    async def remove(self, namespace_id: str, resource_id: str):
        await self.index.delete_documents_by_filter(
            filter=["type={}".format(IndexRecordType.chunk), "chunk.resource_id = '{}'".format(resource_id)])

    async def query(
            self,
            query: str,
            k: int,
            namespace_id: str,
            where: dict
    ) -> List[Tuple[Chunk, float]]:
        raise NotImplementedError()
