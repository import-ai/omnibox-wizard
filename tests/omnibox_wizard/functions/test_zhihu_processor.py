from unittest.mock import AsyncMock, Mock
from pathlib import Path

import pytest

from common.trace_info import TraceInfo
from omnibox_wizard.worker.functions.html_reader.html_reader import HTMLReaderV2
from omnibox_wizard.worker.functions.html_reader.processors.zhihu import (
    ZhihuProcessor,
)
from wizard_common.worker.entity import Task


ZHIHU_SAMPLE_DIR = Path("tmp/parse_html/zhihu")


def read_sample(name: str) -> str:
    return (ZHIHU_SAMPLE_DIR / name).read_text(encoding="utf-8")


@pytest.fixture
def processor() -> ZhihuProcessor:
    return ZhihuProcessor(config=None)


def test_hit_only_zhuanlan_article_urls(processor: ZhihuProcessor):
    assert processor.hit(
        "",
        "https://zhuanlan.zhihu.com/p/1994423521271637277",
    )
    assert not processor.hit(
        "",
        "https://www.zhihu.com/question/123456",
    )
    assert not processor.hit(
        "",
        "https://www.zhihu.com/question/123456/answer/789",
    )
    assert not processor.hit(
        "",
        "https://zhuanlan.zhihu.com/",
    )


@pytest.mark.asyncio
async def test_convert_keeps_title_author_body_and_column_only(
    processor: ZhihuProcessor,
):
    processor.get_images = AsyncMock(return_value=[])

    result = await processor.convert(
        read_sample("sample02.html"),
        "https://zhuanlan.zhihu.com/p/1994423521271637277",
    )

    assert result.title == "马年第一颗雷爆了！烧光500亿，“中国宝马”倒下"

    assert "[象视汽车](https://www.zhihu.com/people/xiangshiqiche)" in result.markdown
    assert (
        "所属专栏：[汽车行业]"
        "(https://www.zhihu.com/column/c_1595837101454635008)" in result.markdown
    )

    assert "岁末年初，当寒冬笼罩中国汽车产业" in result.markdown

    assert "马年第一颗雷爆了" not in result.markdown
    assert "看看车，聊聊车，侃侃车。公众号：象视汽车" not in result.markdown
    assert "编辑于 2026-01-14 09:02" not in result.markdown
    assert "所属专栏 · 1 小时前 更新" not in result.markdown
    assert "最热内容" not in result.markdown


@pytest.mark.asyncio
async def test_convert_preserves_rich_body_structure(
    processor: ZhihuProcessor,
):
    processor.get_images = AsyncMock(return_value=[])

    result = await processor.convert(
        read_sample("sample03.html"),
        "https://zhuanlan.zhihu.com/p/1994561622988055312",
    )

    assert "ACP：一个可能被低估的 Agent 接口协议" not in result.markdown
    assert "问题本质" in result.markdown
    assert "## " in result.markdown
    assert "session/request_permission" in result.markdown
    assert "MCP" in result.markdown


@pytest.mark.asyncio
async def test_convert_extracts_only_body_images_in_source_order(
    processor: ZhihuProcessor,
):
    processor.get_images = AsyncMock(return_value=[])

    await processor.convert(
        read_sample("sample02.html"),
        "https://zhuanlan.zhihu.com/p/1994423521271637277",
    )

    processor.get_images.assert_awaited_once_with(
        [
            (
                "https://pic2.zhimg.com/v2-f211ff81b1de9227e451f19c75554373_1440w.jpg",
                "1",
            ),
            (
                "https://pica.zhimg.com/v2-3c80deb38541129eba983e74c06d2370_1440w.jpg",
                "2",
            ),
            (
                "https://pic4.zhimg.com/v2-fa18a4ca9c66979979e3f92ce72909c3_1440w.jpg",
                "3",
            ),
            (
                "https://picx.zhimg.com/v2-4e9c84aec48d1fb0059da09c3fde8b5f_1440w.jpg",
                "4",
            ),
            (
                "https://pic3.zhimg.com/v2-9c7d3729e97a8fc929117154045558ec_1440w.jpg",
                "5",
            ),
        ]
    )


def test_html_reader_registers_zhihu_processor(monkeypatch):
    monkeypatch.setattr(
        "omnibox_wizard.worker.functions.html_reader.html_reader.HTMLContentExtractor",
        Mock(return_value=Mock()),
    )

    reader = HTMLReaderV2(config=Mock())

    assert isinstance(
        reader.get_processor(
            "",
            "https://zhuanlan.zhihu.com/p/1994561622988055312",
        ),
        ZhihuProcessor,
    )


def test_zhihu_processor_does_not_handle_question_urls(monkeypatch):
    monkeypatch.setattr(
        "omnibox_wizard.worker.functions.html_reader.html_reader.HTMLContentExtractor",
        Mock(return_value=Mock()),
    )

    reader = HTMLReaderV2(config=Mock())

    processor = reader.get_processor(
        "",
        "https://www.zhihu.com/question/123456",
    )

    assert not isinstance(processor, ZhihuProcessor)


@pytest.mark.asyncio
async def test_html_reader_main_uses_zhihu_processor(
    monkeypatch,
):
    monkeypatch.setattr(
        ZhihuProcessor,
        "get_images",
        AsyncMock(return_value=[]),
    )

    reader = HTMLReaderV2(config=Mock())
    task = Task(
        id="zhihu-sample02",
        priority=5,
        namespace_id="test",
        user_id="test",
        function="collect",
        input={
            "html": read_sample("sample02.html"),
            "url": "https://zhuanlan.zhihu.com/p/1994423521271637277",
        },
    )

    result = await reader.main(task, TraceInfo(request_id="test-request"))

    assert result["title"] == "马年第一颗雷爆了！烧光500亿，“中国宝马”倒下"
    assert (
        "[象视汽车](https://www.zhihu.com/people/xiangshiqiche)" in result["markdown"]
    )
    assert "岁末年初，当寒冬笼罩中国汽车产业" in result["markdown"]
    assert "编辑于 2026-01-14 09:02" not in result["markdown"]
    assert "最热内容" not in result["markdown"]
