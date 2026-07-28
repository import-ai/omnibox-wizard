from unittest.mock import AsyncMock

import pytest

from omnibox_wizard.worker.functions.collect_url import ScrapeResponseDto
from omnibox_wizard.worker.functions.rss_item_parser import RssItemParser
from omnibox_wizard.worker.worker import compute_supported_functions


@pytest.mark.asyncio
async def test_rss_item_parser_returns_markdown():
    parser = RssItemParser.__new__(RssItemParser)
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

    markdown = await parser.parse("https://example.com/original", AsyncMock())

    assert markdown == "# Article"
    reader_task = parser.html_reader.main.call_args.args[0]
    assert reader_task.input == {
        "url": "https://example.com/article",
        "html": "<html><body><p>Article</p></body></html>",
        "title": "Article",
    }


@pytest.mark.asyncio
async def test_rss_item_parser_requires_url():
    parser = RssItemParser.__new__(RssItemParser)
    parser.collect_url = AsyncMock()
    parser.html_reader = AsyncMock()

    with pytest.raises(ValueError):
        await parser.parse("", AsyncMock())


def test_parse_rss_item_is_not_a_worker_function():
    task_config = type("TaskConfig", (), {"functions": None})()

    assert "parse_rss_item" not in compute_supported_functions(task_config)
