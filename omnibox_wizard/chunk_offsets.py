from collections.abc import Iterable


def find_chunk_ranges(
    content: str, chunks: Iterable[str], *, chunk_overlap: int = 0
) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    previous_start = 0
    previous_length = 0
    seen_chunks: set[str] = set()
    chunk_overlap = max(0, chunk_overlap)

    for chunk in chunks:
        previous_end = previous_start + previous_length
        search_start = max(
            previous_start, previous_end - chunk_overlap
        )
        if chunk in seen_chunks:
            search_start = previous_end
        elif ranges and search_start == previous_start:
            search_start += 1

        start_index = content.find(chunk, search_start)
        if start_index == -1:
            raise ValueError("chunk text not found in content")

        end_index = start_index + len(chunk)
        ranges.append((start_index, end_index))
        previous_start = start_index
        previous_length = len(chunk)
        seen_chunks.add(chunk)

    return ranges
