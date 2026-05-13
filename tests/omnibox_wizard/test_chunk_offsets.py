import pytest

from omnibox_wizard.chunk_offsets import find_chunk_ranges


def test_find_chunk_ranges_advances_for_repeated_identical_chunks() -> None:
    content = "first\nsame chunk\nmiddle\nsame chunk\nlast\n"

    ranges = find_chunk_ranges(content, ["same chunk", "same chunk"])

    assert ranges == [(6, 16), (24, 34)]


def test_find_chunk_ranges_allows_splitter_overlap() -> None:
    content = "abc def ghi def ghi"

    ranges = find_chunk_ranges(content, ["abc def", "def ghi"], chunk_overlap=3)

    assert ranges == [(0, 7), (4, 11)]


def test_find_chunk_ranges_skips_repeated_chunk_inside_previous_chunk() -> None:
    content = "first\nsame\nmiddle same middle\nsame\n"

    ranges = find_chunk_ranges(
        content, ["same", "middle same middle", "same"], chunk_overlap=128
    )

    assert ranges == [(6, 10), (11, 29), (30, 34)]


def test_find_chunk_ranges_raises_when_chunk_is_missing_after_offset() -> None:
    with pytest.raises(ValueError, match="chunk text not found"):
        find_chunk_ranges("one two", ["one", "missing"])
