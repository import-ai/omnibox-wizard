from unittest.mock import AsyncMock
import re

import pytest

from omnibox_wizard.worker.functions.html_reader.processors.x import XProcessor


ARTICLE_URL = "https://x.com/example/status/123456789"

LOGIN_ARTICLE_HTML = """
<article data-testid="twitterArticleReadView">
  <div data-testid="twitter-article-title">登录态文章标题</div>
  <div data-testid="twitterArticleRichTextView">
    <div data-testid="longformRichTextComponent">
      <div data-contents="true">
        <div data-block="true" class="longform-unstyled">
          <div class="public-DraftStyleDefault-block"><span>第一段正文。</span></div>
        </div>
        <div data-block="true" class="longform-unstyled">
          <div class="public-DraftStyleDefault-block">
            <span>每天自动抓取 X（</span>
            <a href="https://x.com/@reidhannaford">@reidhannaford</a>
            <span>）上关注的账号动态。</span>
          </div>
        </div>
        <div class="css-146c3p1">
          <h1 class="longform-header-one" data-block="true">What Is the Agent Harness?</h1>
        </div>
        <div data-block="true" class="longform-header-two">
          <h2 class="longform-header-two">第一章</h2>
        </div>
        <section data-block="true">
          <div>
            <div>
              <table>
                <tr>
                  <th><span>能力来源</span></th>
                  <th><span>对系统搭建的帮助</span></th>
                </tr>
                <tr>
                  <td><span>产品营销</span></td>
                  <td><span>为智能体提供客户、定位和产品方案上下文</span></td>
                </tr>
              </table>
            </div>
          </div>
        </section>
        <section>
          <img src="https://pbs.twimg.com/media/body-login.jpg" alt="正文图片">
        </section>
      </div>
    </div>
  </div>
</article>
"""

SHARED_ARTICLE_HTML = """
<main>
  <article>
    <h1>分享态文章标题</h1>
    <div class="x-article-body break-words">
      <div class="contents">
        <p><b><strong>分享页的第一段正文。</strong></b></p>
        <h2><br/><span>What a harness actually is</span></h2>
        <h3>第一章</h3>
        <p>正文中的 <a href="https://example.com/source">链接</a>。</p>
        <p>参考账号 <a href="https://x.com/@reidhannaford">@reidhannaford</a>。</p>
        <figure>
          <img src="https://pbs.twimg.com/media/body-share.jpg" alt="正文图片">
        </figure>
      </div>
    </div>
  </article>
  <section class="comments">
    <article><p>这是一条评论，不应被提取。</p></article>
  </section>
</main>
"""

REGULAR_POST_HTML = """
<article data-testid="tweet">
  <div data-testid="User-Name">Example @example</div>
  <div data-testid="tweetText">
    普通 POST 正文，提及
    <a href="https://x.com/@example">@example</a>。
  </div>
</article>
"""


@pytest.fixture
def processor() -> XProcessor:
    return XProcessor(config=None)


@pytest.mark.asyncio
async def test_convert_login_article_keeps_body_and_images(processor: XProcessor):
    processor.get_images = AsyncMock(return_value=[])

    result = await processor.convert(LOGIN_ARTICLE_HTML, ARTICLE_URL)

    assert result.title == "登录态文章标题"
    assert "第一段正文。" in result.markdown
    assert "[reidhannaford](https://x.com/reidhannaford)" in result.markdown
    assert "[@reidhannaford](https://x.com/@reidhannaford)" not in result.markdown
    assert "# What Is the Agent Harness?" in result.markdown
    assert "## 第一章" in result.markdown
    assert "| 能力来源 | 对系统搭建的帮助 |" in result.markdown
    assert "| 产品营销 | 为智能体提供客户、定位和产品方案上下文 |" in result.markdown
    assert "正文图片" in result.markdown
    processor.get_images.assert_awaited_once_with(
        [
            (
                "https://pbs.twimg.com/media/body-login.jpg",
                "正文图片",
            )
        ]
    )


@pytest.mark.asyncio
async def test_convert_shared_article_extracts_article_not_comments(
    processor: XProcessor,
):
    processor.get_images = AsyncMock(return_value=[])

    result = await processor.convert(SHARED_ARTICLE_HTML, ARTICLE_URL)

    assert result.title == "分享态文章标题"
    assert "分享页的第一段正文。" in result.markdown
    assert "**分享页的第一段正文。**" in result.markdown
    assert "****分享页的第一段正文。****" not in result.markdown
    assert "## What a harness actually is" in result.markdown
    assert re.search(r"^##\s*$", result.markdown, re.M) is None
    assert "第一章" in result.markdown
    assert "[链接](https://example.com/source)" in result.markdown
    assert "[reidhannaford](https://x.com/reidhannaford)" in result.markdown
    assert "[@reidhannaford](" not in result.markdown
    assert "正文图片" in result.markdown
    assert "这是一条评论，不应被提取。" not in result.markdown
    processor.get_images.assert_awaited_once_with(
        [
            (
                "https://pbs.twimg.com/media/body-share.jpg",
                "正文图片",
            )
        ]
    )


@pytest.mark.asyncio
async def test_convert_regular_post_does_not_use_article_branch(processor: XProcessor):
    processor.get_images = AsyncMock(return_value=[])

    result = await processor.convert(REGULAR_POST_HTML, ARTICLE_URL)

    assert "普通 POST 正文" in (result.title or "")
    assert "普通 POST 正文" in result.markdown
    assert "[example](https://x.com/example)" in result.markdown
    assert "[@example](" not in result.markdown
