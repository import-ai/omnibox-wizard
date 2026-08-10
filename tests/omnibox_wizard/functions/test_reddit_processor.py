from unittest.mock import AsyncMock, Mock

import pytest
from wizard_common.worker.entity import Image
from bs4 import BeautifulSoup

from omnibox_wizard.worker.functions.html_reader.processors.reddit import (
    RedditProcessor,
)
from omnibox_wizard.worker.functions.html_reader.html_reader import HTMLReaderV2


POST_PATH = "/r/whatisit/comments/1vddifc"
POST_URL = f"https://www.reddit.com{POST_PATH}/snail_trail_on_my_jeans/"

TEXT_POST_HTML = """
<shreddit-post
    id="t3_1vddifc"
    post-title="Fallback title"
    post-type="text"
>
    <h1 slot="title">Snail trail on my jeans?</h1>
    <div property="schema:articleBody">
        <p>First paragraph.</p>
        <p><strong>Second paragraph.</strong></p>
    </div>
</shreddit-post>
"""

FALLBACK_TITLE_POST_HTML = """
<shreddit-post
    id="t3_1vddifc"
    post-title="Fallback title"
    post-type="text"
>
    <div property="schema:articleBody">
        <p>Only body paragraph.</p>
    </div>
</shreddit-post>
"""

IMAGE_URL = "https://i.redd.it/uvb4iwswvehh1.jpeg"

IMAGE_POST_HTML = f"""
<shreddit-post
    id="t3_1vddifc"
    post-title="Image post"
    post-type="image"
>
    <h1 slot="title">Image post</h1>
    <div slot="post-media-container">
        <img
            class="post-background-image-filter"
            src="https://preview.redd.it/background.jpeg"
            alt=""
        >
        <img
            class="media-lightbox-img"
            src="https://preview.redd.it/preview.jpeg"
            alt="Preview image"
        >
        <img
            src="{IMAGE_URL}"
            alt="Original image"
        >
    </div>
</shreddit-post>
"""

GALLERY_IMAGE_URLS = (
    "https://preview.redd.it/gallery-first.jpeg",
    "https://preview.redd.it/gallery-second.jpeg",
)

GALLERY_POST_HTML = f"""
<shreddit-post
    id="t3_1vddifc"
    post-title="Gallery post"
    post-type="gallery"
>
    <h1 slot="title">Gallery post</h1>
    <div slot="post-media-container">
        <img
            class="post-background-image-filter"
            src="{GALLERY_IMAGE_URLS[0]}"
            alt=""
        >
        <img
            class="media-lightbox-img"
            src="{GALLERY_IMAGE_URLS[0]}"
            alt="First image"
        >
        <img
            class="media-lightbox-img"
            src="{GALLERY_IMAGE_URLS[0]}"
            alt="Duplicate first image"
        >
        <img
            class="post-background-image-filter"
            src="{GALLERY_IMAGE_URLS[1]}"
            alt=""
        >
        <img
            class="media-lightbox-img"
            src="{GALLERY_IMAGE_URLS[1]}"
            alt="Second image"
        >
    </div>
</shreddit-post>
"""

GIF_POSTER_URL = "https://preview.redd.it/example.gif?width=640&format=png8"

GIF_POST_HTML = f"""
<shreddit-post
    id="t3_1vddifc"
    post-title="GIF post"
    post-type="gif"
    content-href="https://i.redd.it/example.gif"
>
    <h1 slot="title">GIF post</h1>
    <div slot="post-media-container">
        <img
            slot="poster"
            src="{GIF_POSTER_URL}"
            alt="media poster"
        >
        <img
            class="blurred-error-image"
            src="{GIF_POSTER_URL}"
            alt="媒体错误"
        >
        <source
            src="https://preview.redd.it/example.gif?format=mp4"
        >
    </div>
</shreddit-post>
"""

VIDEO_POSTER_URL = "https://preview.redd.it/video-poster.png"

VIDEO_POST_HTML = f"""
<shreddit-post
    id="t3_1vddifc"
    post-title="Video post"
    post-type="video"
    content-href="https://v.redd.it/example"
>
    <h1 slot="title">Video post</h1>
    <div property="schema:articleBody">
        <p>Video text.</p>
    </div>
    <div slot="post-media-container">
        <img
            slot="poster"
            src="{VIDEO_POSTER_URL}"
            alt="media poster"
        >
        <source
            src="https://v.redd.it/example/HLSPlaylist.m3u8"
        >
    </div>
</shreddit-post>
"""


def _processor() -> RedditProcessor:
    return RedditProcessor(config=Mock())


@pytest.mark.parametrize(
    "url",
    [
        f"https://www.reddit.com{POST_PATH}",
        f"https://www.reddit.com{POST_PATH}/",
        f"https://www.reddit.com{POST_PATH}/snail_trail_on_my_jeans/",
        f"https://reddit.com{POST_PATH}?utm_source=share",
    ],
)
def test_hit_accepts_supported_reddit_post_urls(url: str):
    assert _processor().hit("", url)


@pytest.mark.parametrize(
    "url",
    [
        "https://www.reddit.com/",
        "https://www.reddit.com/r/whatisit/",
        "https://www.reddit.com/gallery/1vddifc",
        "https://www.reddit.com/r/whatisit/comments/",
        f"https://old.reddit.com{POST_PATH}",
        f"https://evilreddit.com{POST_PATH}",
        f"https://example.com{POST_PATH}",
    ],
)
def test_hit_rejects_non_post_and_unsupported_urls(url: str):
    assert not _processor().hit("", url)


async def test_convert_uses_visible_title_and_article_body():
    result = await _processor().convert(TEXT_POST_HTML, POST_URL)

    assert result.title == "Snail trail on my jeans?"
    assert result.markdown == (
        "Snail trail on my jeans?\n\nFirst paragraph.\n\n**Second paragraph.**"
    )
    assert result.images is None


async def test_convert_falls_back_to_post_title_attribute():
    result = await _processor().convert(FALLBACK_TITLE_POST_HTML, POST_URL)

    assert result.title == "Fallback title"
    assert result.markdown == "Fallback title\n\nOnly body paragraph."
    assert result.images is None


async def test_convert_prefers_original_reddit_image():
    downloaded_image = Image(
        name="Original image",
        link=IMAGE_URL,
        data="base64-data",
        mimetype="image/jpeg",
    )
    processor = _processor()
    processor.get_images = AsyncMock(return_value=[downloaded_image])

    result = await processor.convert(IMAGE_POST_HTML, POST_URL)

    processor.get_images.assert_awaited_once_with([(IMAGE_URL, "Original image")])
    assert result.title == "Image post"
    assert result.markdown == (f"Image post\n\n![Original image]({IMAGE_URL})")
    assert result.images == [downloaded_image]


async def test_convert_ignores_empty_poster_before_original_image():
    html = f"""
    <shreddit-post
        id="t3_1vddifc"
        post-title="Image post"
        post-type="image"
    >
        <h1 slot="title">Image post</h1>
        <div slot="post-media-container">
            <img slot="poster" src="" alt="Empty poster">
            <img src="{IMAGE_URL}" alt="Original image">
        </div>
    </shreddit-post>
    """
    processor = _processor()
    processor.get_images = AsyncMock(return_value=[])

    result = await processor.convert(html, POST_URL)

    processor.get_images.assert_awaited_once_with([(IMAGE_URL, "Original image")])
    assert result.markdown == (f"Image post\n\n![Original image]({IMAGE_URL})")


async def test_convert_keeps_remote_image_when_download_fails():
    processor = _processor()
    processor.get_images = AsyncMock(return_value=[])

    result = await processor.convert(IMAGE_POST_HTML, POST_URL)

    processor.get_images.assert_awaited_once_with([(IMAGE_URL, "Original image")])
    assert result.markdown == (f"Image post\n\n![Original image]({IMAGE_URL})")
    assert result.images is None


async def test_convert_falls_back_to_ordered_gallery_images():
    expected_refs = [
        (GALLERY_IMAGE_URLS[0], "First image"),
        (GALLERY_IMAGE_URLS[1], "Second image"),
    ]
    downloaded_images = [
        Image(
            name=alt,
            link=src,
            data="base64-data",
            mimetype="image/jpeg",
        )
        for src, alt in expected_refs
    ]
    processor = _processor()
    processor.get_images = AsyncMock(return_value=downloaded_images)

    result = await processor.convert(GALLERY_POST_HTML, POST_URL)

    processor.get_images.assert_awaited_once_with(expected_refs)
    assert result.title == "Gallery post"
    assert result.markdown == (
        f"Gallery post\n\n"
        f"![First image]({GALLERY_IMAGE_URLS[0]})\n\n"
        f"![Second image]({GALLERY_IMAGE_URLS[1]})"
    )
    assert result.images == downloaded_images


async def test_convert_uses_static_poster_for_gif_post():
    downloaded_image = Image(
        name="media poster",
        link=GIF_POSTER_URL,
        data="base64-data",
        mimetype="image/png",
    )
    processor = _processor()
    processor.get_images = AsyncMock(return_value=[downloaded_image])

    result = await processor.convert(GIF_POST_HTML, POST_URL)

    processor.get_images.assert_awaited_once_with([(GIF_POSTER_URL, "media poster")])
    assert result.title == "GIF post"
    assert result.markdown == (f"GIF post\n\n![media poster]({GIF_POSTER_URL})")
    assert result.images == [downloaded_image]


async def test_convert_preserves_body_markdown_indentation():
    html = """
    <shreddit-post id="t3_1vddifc" post-type="text">
        <h1 slot="title">Structured post</h1>
        <div property="schema:articleBody">
            <ul>
                <li>
                    Outer item
                    <ul>
                        <li>Inner item</li>
                    </ul>
                </li>
            </ul>
            <pre><code>print("hello")</code></pre>
        </div>
    </shreddit-post>
    """

    result = await _processor().convert(html, POST_URL)

    assert "\n    * Inner item" in result.markdown
    assert '\n    print("hello")' in result.markdown


async def test_convert_ignores_media_for_video_post():
    processor = _processor()
    processor.get_images = AsyncMock(return_value=[])

    result = await processor.convert(VIDEO_POST_HTML, POST_URL)

    processor.get_images.assert_not_awaited()
    assert result.title == "Video post"
    assert result.markdown == "Video post\n\nVideo text."
    assert result.images is None


async def test_convert_raises_when_exact_post_is_missing():
    html = """
    <shreddit-post id="t3_other" post-title="Other post">
        <h1 slot="title">Other post</h1>
    </shreddit-post>
    """

    with pytest.raises(
        ValueError,
        match="Reddit post t3_1vddifc was not found",
    ):
        await _processor().convert(html, POST_URL)


async def test_convert_raises_when_post_has_no_content():
    html = """
    <shreddit-post
        id="t3_1vddifc"
        post-type="text"
    ></shreddit-post>
    """

    with pytest.raises(
        ValueError,
        match="Reddit post t3_1vddifc has no content",
    ):
        await _processor().convert(html, POST_URL)


def test_html_reader_registers_reddit_processor(monkeypatch):
    monkeypatch.setattr(
        "omnibox_wizard.worker.functions.html_reader.html_reader.HTMLContentExtractor",
        Mock(return_value=Mock()),
    )
    reader = HTMLReaderV2(config=Mock())

    assert isinstance(
        reader.get_processor("", POST_URL),
        RedditProcessor,
    )


def test_html_reader_registers_bare_reddit_fallback_selector(monkeypatch):
    monkeypatch.setattr(
        "omnibox_wizard.worker.functions.html_reader.html_reader.HTMLContentExtractor",
        Mock(return_value=Mock()),
    )
    reader = HTMLReaderV2(config=Mock())
    url = f"https://reddit.com{POST_PATH}"
    soup = BeautifulSoup(
        "<shreddit-post-text-body>Fallback body</shreddit-post-text-body>",
        "html.parser",
    )

    selector = reader.get_selector(url, soup)

    assert selector is not None
    assert selector.select(url, soup).get_text(" ", strip=True) == "Fallback body"
