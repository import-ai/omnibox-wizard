from typing import List

from common.trace_info import TraceInfo
from wizard.config import VectorConfig
from wizard.entity import Task
from wizard.grimoire.entity.chunk import Chunk, ChunkType
from wizard.grimoire.retriever.vector_db import VectorDB
from wizard.wand.functions.base_function import BaseFunction


def line_level(line: str) -> int:
    return len(line) - len(line.lstrip('#'))


def split_markdown(
        title: str | None = None,
        markdown_text: str | None = None,
        meta_info: dict | None = None
) -> List[Chunk]:
    if not (markdown_text or title):
        raise ValueError("title and markdown_text cannot be None at the same time")
    meta_info = (meta_info or {}) | {"title": title}
    lines: List[str] = markdown_text.split('\n') if markdown_text else []
    body = Chunk(text=markdown_text or title, chunk_type=ChunkType.doc,
                 start_lineno=0, end_lineno=len(lines), **meta_info)
    chunk_list: List[Chunk] = [body]
    if lines:
        chunk_stack: List[Chunk] = []
        previous_lineno: int = 0
        for lineno, line in enumerate(
                lines + ["#"]):  # Add a "#" to make program handle last part without special check.
            if line.startswith('#'):
                chunk = Chunk(
                    text='\n'.join(lines[previous_lineno:lineno]).strip(),
                    chunk_type=ChunkType.section,
                    start_lineno=previous_lineno,
                    end_lineno=lineno,
                    **meta_info
                )
                current_level = line_level(lines[chunk.start_lineno])
                while len(chunk_stack) > 0 and line_level(lines[chunk_stack[-1].start_lineno]) >= current_level:
                    chunk_stack.pop()

                if len(chunk_stack) > 0:
                    chunk.parent_chunk_id = chunk_stack[-1].chunk_id
                if current_level > 0:
                    chunk_stack.append(chunk)

                if lineno == len(lines) and previous_lineno == 0:  # 如果当前 chunk 是整个全文，为避免重复，遂跳过
                    continue

                chunk_list.append(chunk)
                previous_lineno = lineno

    return chunk_list


class DeleteIndex(BaseFunction):
    def __init__(self, config: VectorConfig):
        self.vector_db: VectorDB = VectorDB(config)

    async def async_init(self):
        await self.vector_db.async_init()

    async def run(self, task: Task, trace_info: TraceInfo) -> dict:
        input_data = task.input
        namespace_id: str = task.namespace_id
        resource_id: str = input_data["resource_id"]
        await self.vector_db.remove(namespace_id, resource_id)
        return {"success": True}


class CreateOrUpdateIndex(DeleteIndex):

    async def run(self, task: Task, trace_info: TraceInfo) -> dict:
        input_data = task.input
        resource_id: str = input_data["meta_info"]["resource_id"]
        await self.vector_db.remove(task.namespace_id, resource_id)

        title: str = input_data.get("title", "")
        content: str = input_data.get("content", "")
        if not title and not content:
            return {"success": False, "error": "Both title and content cannot be None"}

        meta_info: dict = input_data["meta_info"] | {"namespace_id": task.namespace_id}
        chunk_list: List[Chunk] = split_markdown(title, content, meta_info)
        await self.vector_db.insert(task.namespace_id, chunk_list)
        return {"success": True}


__all__ = ["DeleteIndex", "CreateOrUpdateIndex"]
