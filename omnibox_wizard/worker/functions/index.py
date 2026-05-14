from typing import List

from langchain_text_splitters import MarkdownTextSplitter

from common.trace_info import TraceInfo
from omnibox_wizard.chunk_offsets import find_chunk_ranges
from omnibox_wizard.worker.config import WorkerConfig
from omnibox_wizard.worker.functions.base_function import BaseFunction
from wizard_common.grimoire.entity.chunk import Chunk, ChunkType
from wizard_common.grimoire.entity.message import Message
from wizard_common.grimoire.entity.retrieval import (
    char_range_to_line_range,
    format_line_range,
)
from wizard_common.grimoire.retriever.weaviate_vector_db import WeaviateVectorDB
from wizard_common.worker.entity import Task


class DeleteIndex(BaseFunction):
    def __init__(self, config: WorkerConfig):
        self.vector_db: WeaviateVectorDB = WeaviateVectorDB(config.vector)

    async def run(self, task: Task, trace_info: TraceInfo) -> dict:
        input_data = task.input
        namespace_id: str = task.namespace_id
        resource_id: str = input_data["resource_id"]
        await self.vector_db.remove_chunks(namespace_id, resource_id)
        return {"success": True}


class UpsertIndex(DeleteIndex):
    def __init__(self, config: WorkerConfig):
        super().__init__(config)
        self.chunk_overlap = config.task.spliter.chunk_overlap
        self.spliter = MarkdownTextSplitter(
            chunk_size=config.task.spliter.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )

    async def run(self, task: Task, trace_info: TraceInfo) -> dict:
        input_data = task.input
        resource_id: str = input_data["meta_info"]["resource_id"]
        await self.vector_db.remove_chunks(task.namespace_id, resource_id)

        title: str = input_data.get("title", "")
        content: str = input_data.get("content", "")
        if not title and not content:
            return {"success": False, "error": "Both title and content cannot be None"}

        meta_info: dict = input_data["meta_info"] | {"namespace_id": task.namespace_id}
        chunks = self.spliter.split_text(content)
        if not chunks:
            chunks.append("")

        chunk_list: List[Chunk] = []
        for chunk, (start_index, end_index) in zip(
            chunks,
            find_chunk_ranges(content, chunks, chunk_overlap=self.chunk_overlap),
            strict=True,
        ):
            chunk_list.append(
                Chunk(
                    title=title,
                    text=chunk,
                    chunk_type=ChunkType.snippet,
                    start_index=start_index,
                    end_index=end_index,
                    line_range=format_line_range(
                        char_range_to_line_range(content, start_index, end_index)
                    ),
                    **meta_info,
                )
            )
        await self.vector_db.insert_chunks(task.namespace_id, chunk_list)
        return {"success": True}


class UpsertMessageIndex(BaseFunction):
    def __init__(self, config: WorkerConfig):
        super().__init__()
        self.vector_db: WeaviateVectorDB = WeaviateVectorDB(config.vector)

    async def run(self, task: Task, trace_info: TraceInfo) -> dict:
        message = Message(**task.input)
        await self.vector_db.upsert_message(task.namespace_id, task.user_id, message)
        return {"success": True}


class DeleteConversation(BaseFunction):
    def __init__(self, config: WorkerConfig):
        super().__init__()
        self.vector_db: WeaviateVectorDB = WeaviateVectorDB(config.vector)

    async def run(self, task: Task, trace_info: TraceInfo) -> dict:
        conversation_id: str = task.input.get("conversation_id", "")
        if conversation_id == "":
            return {"success": False, "error": "conversation_id is required"}
        await self.vector_db.remove_conversation(task.namespace_id, conversation_id)
        return {"success": True}


__all__ = ["DeleteIndex", "UpsertIndex", "UpsertMessageIndex", "DeleteConversation"]
