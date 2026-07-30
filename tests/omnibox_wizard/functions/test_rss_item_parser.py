from unittest.mock import AsyncMock

import pytest

from omnibox_wizard.worker.functions.collect_url import ScrapeResponseDto
from omnibox_wizard.worker.functions.rss_item_parser import RssItemParser
from omnibox_wizard.worker.worker import compute_supported_functions


def _make_parser() -> RssItemParser:
    parser = RssItemParser.__new__(RssItemParser)
    parser.collect_url = AsyncMock()
    parser.collect_url._scrape_url.return_value = ScrapeResponseDto(
        final_url="https://example.com/article",
        html="<html><body><p>Scraped</p></body></html>",
        title="Scraped",
    )
    parser.html_reader = AsyncMock()
    parser.html_reader.main.return_value = {
        "title": "Article",
        "markdown": "# Article",
        "images": [{"link": "https://example.com/image.png"}],
        "next_tasks": [{"function": "extract_tags"}],
    }
    return parser


@pytest.mark.asyncio
async def test_parse_uses_embedded_content_without_scraping():
    parser = _make_parser()

    markdown = await parser.parse(
        "https://example.com/original",
        "<article><p>Embedded</p></article>",
        AsyncMock(),
    )

    assert markdown == "# Article"
    # Embedded content path must not fetch the link.
    parser.collect_url._scrape_url.assert_not_awaited()
    reader_task = parser.html_reader.main.call_args.args[0]
    assert reader_task.input == {
        "url": "https://example.com/original",
        "html": "<article><p>Embedded</p></article>",
        "title": "",
    }


@pytest.mark.asyncio
async def test_parse_scrapes_when_no_content():
    parser = _make_parser()

    markdown = await parser.parse("https://example.com/original", "", AsyncMock())

    assert markdown == "# Article"
    parser.collect_url._scrape_url.assert_awaited_once_with(
        "https://example.com/original"
    )
    reader_task = parser.html_reader.main.call_args.args[0]
    assert reader_task.input == {
        "url": "https://example.com/article",
        "html": "<html><body><p>Scraped</p></body></html>",
        "title": "Scraped",
    }


@pytest.mark.asyncio
async def test_parse_requires_url_or_content():
    parser = _make_parser()

    with pytest.raises(ValueError):
        await parser.parse("", "", AsyncMock())


def test_parse_rss_item_is_not_a_worker_function():
    task_config = type("TaskConfig", (), {"functions": None})()

    assert "parse_rss_item" not in compute_supported_functions(task_config)
