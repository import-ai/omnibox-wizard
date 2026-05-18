from langchain_text_splitters import MarkdownTextSplitter

from omnibox_wizard.chunk_offsets import find_chunk_ranges
from wizard_common.grimoire.entity.chunk import Chunk, ChunkType
from wizard_common.grimoire.entity.retrieval import (
    char_range_to_line_range,
    format_line_range,
)


def build_resource_chunks(
    *,
    title: str,
    content: str,
    metadata: dict,
    chunk_size: int,
    chunk_overlap: int,
) -> list[Chunk]:
    splitter = MarkdownTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )
    texts = splitter.split_text(content)
    if not texts:
        texts.append("")

    chunks: list[Chunk] = []
    for text, (start_index, end_index) in zip(
        texts,
        find_chunk_ranges(content, texts, chunk_overlap=chunk_overlap),
        strict=True,
    ):
        chunks.append(
            Chunk(
                title=title,
                text=text,
                chunk_type=ChunkType.snippet,
                start_index=start_index,
                end_index=end_index,
                line_range=format_line_range(
                    char_range_to_line_range(content, start_index, end_index)
                ),
                **metadata,
            )
        )
    return chunks
