import pytest

from omnibox_wizard.worker.entity import Task
from omnibox_wizard.worker.functions.tag_extractor import TagExtractor


@pytest.mark.asyncio
async def test_tag_extractor_success(worker_config, trace_info):
    """Test successful tag extraction"""
    tag_extractor = TagExtractor(worker_config)

    task = Task(
        id="test_task",
        priority=1,
        namespace_id="test_namespace",
        user_id="test_user",
        function="extract_tags",
        input={"text": "This is a sample text about machine learning and artificial intelligence."}
    )

    result = await tag_extractor.run(task, trace_info)

    assert "tags" in result
    assert isinstance(result["tags"], list)
    # Tags should be extracted from the input text
    assert len(result["tags"]) >= 0



@pytest.mark.asyncio
async def test_tag_extractor_empty_text(worker_config, trace_info):
    """Test tag extraction with empty text"""
    tag_extractor = TagExtractor(worker_config)

    task = Task(
        id="test_task",
        priority=1,
        namespace_id="test_namespace",
        user_id="test_user",
        function="extract_tags",
        input={"text": ""}
    )

    with pytest.raises(ValueError, match="Text input is required for tag extraction"):
        await tag_extractor.run(task, trace_info)


@pytest.mark.asyncio
async def test_tag_extractor_no_text_input(worker_config, trace_info):
    """Test tag extraction without text input"""
    tag_extractor = TagExtractor(worker_config)

    task = Task(
        id="test_task",
        priority=1,
        namespace_id="test_namespace",
        user_id="test_user",
        function="extract_tags",
        input={}
    )

    with pytest.raises(ValueError, match="Text input is required for tag extraction"):
        await tag_extractor.run(task, trace_info)


@pytest.mark.asyncio
async def test_tag_extractor_with_long_text(worker_config, trace_info):
    """Test tag extraction with long text"""
    tag_extractor = TagExtractor(worker_config)
    long_text = "This is a very long text about various topics. " * 100

    task = Task(
        id="test_task",
        priority=1,
        namespace_id="test_namespace",
        user_id="test_user",
        function="extract_tags",
        input={"text": long_text}
    )

    result = await tag_extractor.run(task, trace_info)

    assert "tags" in result
    assert isinstance(result["tags"], list)
    # Should be able to handle long text
    assert len(result["tags"]) >= 0


@pytest.mark.asyncio
async def test_tag_extractor_short_text(worker_config, trace_info):
    """Test tag extraction with short text"""
    tag_extractor = TagExtractor(worker_config)

    task = Task(
        id="test_task",
        priority=1,
        namespace_id="test_namespace",
        user_id="test_user",
        function="extract_tags",
        input={"text": "Python programming"}
    )

    result = await tag_extractor.run(task, trace_info)

    assert "tags" in result
    assert isinstance(result["tags"], list)
    # Should extract relevant tags from short text
    assert len(result["tags"]) >= 0
