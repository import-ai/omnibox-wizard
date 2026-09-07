from unittest.mock import AsyncMock, Mock

import pytest

from common.trace_info import TraceInfo
from omnibox_wizard.worker.functions.html_reader.html_reader import HTMLReaderV2
from omnibox_wizard.worker.functions.html_reader.processors.zhihu import (
    ZhihuProcessor,
)
from wizard_common.worker.entity import Task


SAMPLE_ARTICLE_HTML = """
<html>
  <head>
    <title>(2 封私信) 马年第一颗雷爆了！烧光500亿，“中国宝马”倒下 - 知乎</title>
  </head>
  <body>
    <article class="Post-Main">
      <header class="Post-Header">
        <h1 class="Post-Title">马年第一颗雷爆了！烧光500亿，“中国宝马”倒下</h1>
        <div class="Post-Author">
          <img class="AuthorInfo-avatar" src="https://img.example.com/avatar.jpg">
          <a class="UserLink-link" href="//www.zhihu.com/people/xiangshiqiche">
            象视汽车
          </a>
          <div class="AuthorInfo-detail">看看车，聊聊车，侃侃车。公众号：象视汽车</div>
        </div>
        <a href="https://www.zhihu.com/column/c_1595837101454635008">
          收录于 · 汽车行业
        </a>
      </header>
      <div class="Post-RichText">
        <p>岁末年初，当寒冬笼罩中国汽车产业。</p>
        <p>正文内容只保留文章主体。</p>
        <img src="https://pic2.zhimg.com/body-1.jpg">
        <img src="https://pica.zhimg.com/body-2.jpg">
        <img src="https://pic4.zhimg.com/body-3.jpg">
        <img src="https://picx.zhimg.com/body-4.jpg">
        <img src="https://pic3.zhimg.com/body-5.jpg">
      </div>
      <div class="ContentItem-time">编辑于 2026-01-14 09:02 · 广东</div>
      <div class="Recommendations-Main">最热内容 推荐文章</div>
    </article>
  </body>
</html>
"""

SAMPLE_RICH_ARTICLE_HTML = """
<html>
  <body>
    <article class="Post-Main">
      <header class="Post-Header">
        <h1 class="Post-Title">ACP：一个可能被低估的 Agent 接口协议</h1>
        <a href="https://www.zhihu.com/column/c_1981500933335711840">
          收录于 · 技术思考
        </a>
      </header>
      <div class="Post-RichText">
        <p>协议解决了 Agent 和客户端之间的协作问题。</p>
        <h2>0. 问题本质</h2>
        <ul>
          <li>每个 Agent 都有自己的 API 设计</li>
          <li>客户端需要统一能力</li>
        </ul>
        <pre><code>session/request_permission</code></pre>
        <p>MCP 可以连接外部工具和数据源。</p>
      </div>
    </article>
  </body>
</html>
"""


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
        SAMPLE_ARTICLE_HTML,
        "https://zhuanlan.zhihu.com/p/1994423521271637277",
    )

    assert result.title == "马年第一颗雷爆了！烧光500亿，“中国宝马”倒下"
    assert (
        "[象视汽车](https://www.zhihu.com/people/xiangshiqiche)" not in result.markdown
    )
    assert "看看车，聊聊车，侃侃车。公众号：象视汽车" not in result.markdown
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
        SAMPLE_RICH_ARTICLE_HTML,
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
        SAMPLE_ARTICLE_HTML,
        "https://zhuanlan.zhihu.com/p/1994423521271637277",
    )

    processor.get_images.assert_awaited_once_with(
        [
            (
                "https://pic2.zhimg.com/body-1.jpg",
                "1",
            ),
            (
                "https://pica.zhimg.com/body-2.jpg",
                "2",
            ),
            (
                "https://pic4.zhimg.com/body-3.jpg",
                "3",
            ),
            (
                "https://picx.zhimg.com/body-4.jpg",
                "4",
            ),
            (
                "https://pic3.zhimg.com/body-5.jpg",
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
            "html": SAMPLE_ARTICLE_HTML,
            "url": "https://zhuanlan.zhihu.com/p/1994423521271637277",
        },
    )

    result = await reader.main(task, TraceInfo(request_id="test-request"))

    assert result["title"] == "马年第一颗雷爆了！烧光500亿，“中国宝马”倒下"
    assert (
        "[象视汽车](https://www.zhihu.com/people/xiangshiqiche)"
        not in result["markdown"]
    )
    assert "看看车，聊聊车，侃侃车。公众号：象视汽车" not in result["markdown"]
    assert "岁末年初，当寒冬笼罩中国汽车产业" in result["markdown"]
    assert "编辑于 2026-01-14 09:02" not in result["markdown"]
    assert "最热内容" not in result["markdown"]
