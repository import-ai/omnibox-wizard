from typing import List

from langchain_text_splitters import MarkdownTextSplitter

from common.trace_info import TraceInfo
from wizard.config import WorkerConfig
from wizard.entity import Task
from wizard.grimoire.entity.chunk import Chunk, ChunkType
from wizard.grimoire.retriever.vector_db import VectorDB
from wizard.wand.functions.base_function import BaseFunction


class DeleteIndex(BaseFunction):
    def __init__(self, config: WorkerConfig):
        self.vector_db: VectorDB = VectorDB(config.vector)

    async def run(self, task: Task, trace_info: TraceInfo) -> dict:
        input_data = task.input
        namespace_id: str = task.namespace_id
        resource_id: str = input_data["resource_id"]
        await self.vector_db.remove(namespace_id, resource_id)
        return {"success": True}


class UpsertIndex(DeleteIndex):

    def __init__(self, config: WorkerConfig):
        super().__init__(config)
        self.spliter = MarkdownTextSplitter(
            chunk_size=config.task.spliter.chunk_size,
            chunk_overlap=config.task.spliter.chunk_overlap
        )

    async def run(self, task: Task, trace_info: TraceInfo) -> dict:
        input_data = task.input
        resource_id: str = input_data["meta_info"]["resource_id"]
        await self.vector_db.remove(task.namespace_id, resource_id)

        title: str = input_data.get("title", "")
        content: str = input_data.get("content", "")
        if not title and not content:
            return {"success": False, "error": "Both title and content cannot be None"}

        meta_info: dict = input_data["meta_info"] | {"namespace_id": task.namespace_id}
        chunks = self.spliter.split_text(content)

        chunk_list: List[Chunk] = [Chunk(
            title=title, text=chunk, chunk_type=ChunkType.snippet, start_index=content.index(chunk),
            end_index=content.index(chunk) + len(chunk), **meta_info
        ) for chunk in chunks]
        await self.vector_db.insert(task.namespace_id, chunk_list)
        return {"success": True}


__all__ = ["DeleteIndex", "UpsertIndex"]
