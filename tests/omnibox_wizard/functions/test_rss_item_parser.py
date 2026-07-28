from unittest.mock import AsyncMock

import pytest

from omnibox_wizard.worker.functions.collect_url import ScrapeResponseDto
from omnibox_wizard.worker.functions.rss_item_parser import RssItemParserFunction
from omnibox_wizard.worker.worker import compute_supported_functions
from wizard_common.worker.entity import Task


@pytest.mark.asyncio
async def test_rss_item_parser_returns_only_markdown():
    parser = RssItemParserFunction.__new__(RssItemParserFunction)
    parser.collect_url = AsyncMock()
    parser.collect_url._scrape_url.return_value = ScrapeResponseDto(
        final_url="https://example.com/article",
        html="<html><body><p>Article</p></body></html>",
        title="Article",
    )
    parser.html_reader = AsyncMock()
    parser.html_reader.main.return_value = {
        "title": "Article",
        "markdown": "# Article",
        "images": [{"link": "https://example.com/image.png"}],
        "next_tasks": [{"function": "extract_tags"}],
    }
    task = Task(
        id="task-1",
        priority=5,
        namespace_id="namespace-1",
        user_id="user-1",
        function="parse_rss_item",
        input={"url": "https://example.com/original"},
    )

    result = await parser.run(task, AsyncMock())

    assert result == {"markdown": "# Article"}
    reader_task = parser.html_reader.main.call_args.args[0]
    assert reader_task.input == {
        "url": "https://example.com/article",
        "html": "<html><body><p>Article</p></body></html>",
        "title": "Article",
    }


def test_rss_item_parser_is_enabled_by_default():
    task_config = type("TaskConfig", (), {"functions": None})()

    assert "parse_rss_item" in compute_supported_functions(task_config)
