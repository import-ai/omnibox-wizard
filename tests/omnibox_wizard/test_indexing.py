from omnibox_wizard.indexing import build_resource_chunks


def test_build_resource_chunks_preserves_metadata_and_line_ranges() -> None:
    chunks = build_resource_chunks(
        title="Doc",
        content="intro\nsame chunk\nmiddle\nsame chunk\n",
        metadata={
            "namespace_id": "ns_1",
            "resource_id": "resource_1",
            "parent_id": "parent_1",
            "resource_tag_ids": ["tag_1"],
            "resource_tag_names": ["alpha"],
        },
        chunk_size=10,
        chunk_overlap=0,
    )

    same_chunks = [chunk for chunk in chunks if chunk.text == "same"]
    assert [chunk.line_range for chunk in same_chunks] == ["2-2", "4-4"]
    assert same_chunks[0].resource_id == "resource_1"
    assert same_chunks[0].parent_id == "parent_1"
    assert same_chunks[0].resource_tag_ids == ["tag_1"]
    assert same_chunks[0].resource_tag_names == ["alpha"]


def test_build_resource_chunks_keeps_empty_content_indexable() -> None:
    chunks = build_resource_chunks(
        title="Empty",
        content="",
        metadata={
            "resource_id": "resource_1",
            "parent_id": "parent_1",
        },
        chunk_size=1024,
        chunk_overlap=128,
    )

    assert len(chunks) == 1
    assert chunks[0].title == "Empty"
    assert chunks[0].text == ""
    assert chunks[0].start_index == 0
    assert chunks[0].end_index == 0
    assert chunks[0].line_range == "1-1"
