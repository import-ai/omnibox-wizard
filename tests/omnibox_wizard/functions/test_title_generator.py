import pytest

from omnibox_wizard.worker.entity import Task
from omnibox_wizard.worker.functions.title_generator import TitleGenerator


@pytest.mark.asyncio
async def test_title_generator_success(worker_config, trace_info):
    """Test successful title generation"""
    title_generator = TitleGenerator(worker_config)

    task = Task(
        id="test_task",
        priority=1,
        namespace_id="test_namespace",
        user_id="test_user",
        function="generate_title",
        input={"text": "This is a comprehensive guide on machine learning algorithms and their practical applications in modern software development."}
    )

    result = await title_generator.run(task, trace_info)

    assert "title" in result
    assert isinstance(result["title"], str)
    # Title should be non-empty
    assert len(result["title"]) > 0


@pytest.mark.asyncio
async def test_title_generator_empty_text(worker_config, trace_info):
    """Test title generation with empty text"""
    title_generator = TitleGenerator(worker_config)

    task = Task(
        id="test_task",
        priority=1,
        namespace_id="test_namespace",
        user_id="test_user",
        function="generate_title",
        input={"text": ""}
    )

    with pytest.raises(ValueError, match="Text input is required for title generation"):
        await title_generator.run(task, trace_info)


@pytest.mark.asyncio
async def test_title_generator_no_text_input(worker_config, trace_info):
    """Test title generation without text input"""
    title_generator = TitleGenerator(worker_config)

    task = Task(
        id="test_task",
        priority=1,
        namespace_id="test_namespace",
        user_id="test_user",
        function="generate_title",
        input={}
    )

    with pytest.raises(ValueError, match="Text input is required for title generation"):
        await title_generator.run(task, trace_info)


@pytest.mark.asyncio
async def test_title_generator_with_long_text(worker_config, trace_info):
    """Test title generation with long text"""
    title_generator = TitleGenerator(worker_config)
    long_text = "This is a very long article about artificial intelligence, machine learning, deep learning, neural networks, and various other advanced computational techniques used in modern data science. " * 50

    task = Task(
        id="test_task",
        priority=1,
        namespace_id="test_namespace",
        user_id="test_user",
        function="generate_title",
        input={"text": long_text}
    )

    result = await title_generator.run(task, trace_info)

    assert "title" in result
    assert isinstance(result["title"], str)
    # Should be able to handle long text and generate concise title
    assert len(result["title"]) > 0


@pytest.mark.asyncio
async def test_title_generator_short_text(worker_config, trace_info):
    """Test title generation with short text"""
    title_generator = TitleGenerator(worker_config)

    task = Task(
        id="test_task",
        priority=1,
        namespace_id="test_namespace",
        user_id="test_user",
        function="generate_title",
        input={"text": "Python programming basics"}
    )

    result = await title_generator.run(task, trace_info)

    assert "title" in result
    assert isinstance(result["title"], str)
    # Should generate a relevant title from short text
    assert len(result["title"]) > 0


@pytest.mark.asyncio
async def test_title_generator_chinese_text(worker_config, trace_info):
    """Test title generation with Chinese text"""
    title_generator = TitleGenerator(worker_config)

    task = Task(
        id="test_task",
        priority=1,
        namespace_id="test_namespace",
        user_id="test_user",
        function="generate_title",
        input={"text": "这是一篇关于人工智能和机器学习在现代科技发展中的重要作用的文章。"}
    )

    result = await title_generator.run(task, trace_info)

    assert "title" in result
    assert isinstance(result["title"], str)
    # Should generate a title for Chinese text
    assert len(result["title"]) > 0