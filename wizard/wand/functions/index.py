from typing import List

from wizard.grimoire.entity.chunk import Chunk, ChunkType
from wizard.grimoire.retriever.vector_db import VectorDB
from wizard.wand.functions.base_function import BaseFunction


def line_level(line: str) -> int:
    return len(line) - len(line.lstrip('#'))


def split_markdown(namespace: str, resource_id: str, title: str, markdown_text: str) -> List[Chunk]:
    common_info = {"resource_id": resource_id, "namespace": namespace, "title": title}
    lines: List[str] = markdown_text.split('\n')
    body = Chunk(text=f"title: {title}\n" + markdown_text, chunk_type=ChunkType.doc,
                 start_lineno=0, end_lineno=len(lines), **common_info)
    chunk_list: List[Chunk] = [body]
    chunk_stack: List[Chunk] = []
    previous_lineno: int = 0
    for lineno, line in enumerate(lines + ["#"]):  # Add a "#" to make program handle last part without special check.
        if line.startswith('#'):
            chunk = Chunk(
                text='\n'.join([f"title: {title}"] + lines[previous_lineno:lineno]).strip(),
                chunk_type=ChunkType.section,
                start_lineno=previous_lineno,
                end_lineno=lineno,
                **common_info
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


class CreateOrUpdateIndex(BaseFunction):
    def __init__(self, vector_db: VectorDB):
        self.vector_db: VectorDB = vector_db

    async def run(self, input_data: dict) -> dict:
        namespace_id: str = input_data["namespace_id"]
        resource_id: str = input_data["resource_id"]
        title: str = input_data["title"]
        content: str = input_data["content"]
