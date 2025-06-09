from typing import List, Tuple

from meilisearch_python_sdk import AsyncClient
from meilisearch_python_sdk.types import Filter
from openai import AsyncOpenAI

from wizard.config import VectorConfig
from wizard.grimoire.entity.chunk import Chunk
from wizard.grimoire.entity.index_record import IndexRecord, IndexRecordType


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
