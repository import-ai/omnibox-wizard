from wizard_common.grimoire.entity.chunk import (
    Chunk,
    ChunkType,
    ResourceChunkRetrieval,
)
from wizard_common.grimoire.entity.retrieval import (
    Citation,
    char_range_to_line_range,
    format_cite_marker,
    format_line_range,
    make_citation_id,
    make_citation_slug,
)
from omnibox_wizard.chunk_offsets import find_chunk_ranges


def test_citation_prompt_includes_marker() -> None:
    citation = Citation(
        id="C1-water-temperature-L12-18",
        title="Coffee Guide",
        snippet="Water temperature should stay stable.",
        link="resource-id",
    )

    prompt = citation.to_prompt()

    assert 'id="C1-water-temperature-L12-18"' in prompt
    assert 'cite_marker="[[1]](C1-water-temperature-L12-18)"' in prompt


def test_legacy_numeric_citation_ids_are_not_prompted() -> None:
    for legacy_id in (-1, "-1", 1, "1"):
        citation = Citation(
            id=legacy_id,
            title="Legacy",
            snippet="Legacy snippet",
            link="resource-id",
        )

        prompt = citation.to_prompt()

        assert citation.id == ""
        assert 'id="' not in prompt
        assert "cite_marker" not in prompt


def test_citation_slug_uses_two_to_three_meaningful_words() -> None:
    assert (
        make_citation_slug(
            "OpenAI API Pricing Reference",
            "Model pricing for GPT usage tiers",
        )
        == "openai-api-pricing"
    )
    assert make_citation_slug("Untitled.md", "") == "source"
    assert make_citation_slug("手冲咖啡", "水温建议控制在 90 度") == "shou-chong-ka"
    assert (
        make_citation_slug("测试一下啊超长的文本", "The old clock tower stood silent.")
        == "ce-shi-yi"
    )
    assert make_citation_slug("Café résumé", "naïve façade") == "cafe-resume-naive"


def test_citation_id_and_marker_helpers() -> None:
    citation_id = make_citation_id(
        2,
        "Coffee Guide",
        "Water temperature should stay stable.",
        "12-18",
    )

    assert citation_id == "C2-coffee-guide-water-L12-18"
    assert format_cite_marker(citation_id) == "[[2]](C2-coffee-guide-water-L12-18)"


def test_chinese_citation_id_is_ascii_transliterated() -> None:
    citation_id = make_citation_id(
        2,
        "测试一下啊超长的文本",
        "The old clock tower stood silent.",
        "1-1",
    )

    assert citation_id == "C2-ce-shi-yi-L1-1"
    assert citation_id.isascii()


def test_char_range_to_line_range_converts_document_offsets() -> None:
    content = "line1\nline2\nline3\n"

    line_range = char_range_to_line_range(content, 6, 17)

    assert line_range == {"start": 2, "end": 3}
    assert format_line_range(line_range) == "2-3"


def test_repeated_chunk_text_maps_to_later_line_ranges() -> None:
    content = "intro\nsame chunk\nmiddle\nsame chunk\n"

    ranges = find_chunk_ranges(content, ["same chunk", "same chunk"])
    line_ranges = [
        format_line_range(char_range_to_line_range(content, start_index, end_index))
        for start_index, end_index in ranges
    ]

    assert ranges == [(6, 16), (24, 34)]
    assert line_ranges == ["2-2", "4-4"]


def test_resource_chunk_prompt_includes_line_range_citation_id() -> None:
    chunk = Chunk(
        title="Clock Tower",
        text="The old clock tower.",
        chunk_type=ChunkType.snippet,
        resource_id="resource-id",
        parent_id="parent-id",
        start_index=6,
        end_index=26,
        line_range="2-3",
    )
    retrieval = ResourceChunkRetrieval(chunk=chunk)
    citation = retrieval.to_citation()
    retrieval.id = make_citation_id(
        1, citation.title, citation.snippet, chunk.line_range
    )

    prompt = retrieval.to_prompt()

    assert retrieval.id == "C1-clock-tower-old-L2-3"
    assert 'line_range="2-3"' in prompt
    assert 'cite_marker="[[1]](C1-clock-tower-old-L2-3)"' in prompt
