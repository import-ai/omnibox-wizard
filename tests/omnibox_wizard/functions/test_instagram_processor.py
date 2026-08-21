import json
import httpx
from unittest.mock import AsyncMock, Mock

import pytest
from wizard_common.worker.entity import Image
from opentelemetry import trace

from omnibox_wizard.worker.functions.html_reader.processors.instagram import (
    InstagramProcessor,
)
from omnibox_wizard.worker.functions.html_reader.html_reader import (
    HTMLReaderV2,
)


def _processor() -> InstagramProcessor:
    return InstagramProcessor(config=Mock())


@pytest.mark.parametrize(
    ("url", "shortcode"),
    [
        (
            "https://www.instagram.com/p/DcFzoFogOFC",
            "DcFzoFogOFC",
        ),
        (
            "https://www.instagram.com/p/Db8WEVXGWDA/",
            "Db8WEVXGWDA",
        ),
        (
            "https://www.instagram.com/p/DcOI0PtF-j5/"
            "?utm_source=ig_web_copy_link&igsh=sample",
            "DcOI0PtF-j5",
        ),
    ],
)
def test_accepts_supported_instagram_post_urls(
    url: str,
    shortcode: str,
):
    processor = _processor()

    assert processor.hit("", url) is True
    assert processor._extract_shortcode(url) == shortcode


@pytest.mark.parametrize(
    "url",
    [
        "https://www.instagram.com/",
        "https://www.instagram.com/p/",
        "https://www.instagram.com/reel/DcFzoFogOFC/",
        "https://www.instagram.com/reels/DcFzoFogOFC/",
        "https://www.instagram.com/tutorcircle/p/DcFzoFogOFC/",
        "http://www.instagram.com/p/DcFzoFogOFC/",
        "https://instagram.com/p/DcFzoFogOFC/",
        "https://www.instagram.com.evil.example/p/DcFzoFogOFC/",
        "https://www.instagram.com/p/DcFzoFogOFC/comments/",
    ],
)
def test_rejects_unsupported_instagram_urls(url: str):
    assert _processor().hit("", url) is False


def _json_html(*documents: object) -> str:
    return "".join(
        f'<script type="application/json">{json.dumps(document)}</script>'
        for document in documents
    )


def test_find_image_media_by_shortcode_and_deduplicate_media_id():
    target = {
        "pk": "3962138827016462528",
        "code": "Db8WEVXGWDA",
        "media_type": 8,
        "product_type": "carousel_container",
        "carousel_media": [],
    }
    unrelated = {
        "pk": "unrelated-media",
        "code": "OtherPost01",
        "media_type": 1,
        "image_versions2": {"candidates": []},
    }
    html = _json_html(
        {"payload": {"items": [unrelated, target]}},
        {"duplicate": target},
    )

    media = InstagramProcessor._find_image_media(
        html,
        "Db8WEVXGWDA",
    )

    assert media == target


@pytest.mark.parametrize(
    "reverse_order",
    [False, True],
)
def test_find_image_media_prefers_complete_duplicate_record(
    reverse_order: bool,
):
    complete = {
        "pk": "duplicate-carousel-media",
        "code": "DuplicateCarousel01",
        "media_type": 8,
        "caption": {
            "text": "Complete caption",
        },
        "carousel_media": [
            {
                "image_versions2": {
                    "candidates": [
                        _image_candidate(
                            "duplicate-first",
                            1080,
                            1350,
                        )
                    ]
                }
            },
            {
                "image_versions2": {
                    "candidates": [
                        _image_candidate(
                            "duplicate-second",
                            1080,
                            1350,
                        )
                    ]
                }
            },
        ],
    }
    summary = {
        "pk": "duplicate-carousel-media",
        "code": "DuplicateCarousel01",
        "media_type": 8,
        "caption": {
            "text": "Complete caption",
        },
        "carousel_media_count": 2,
    }
    records = [complete, summary]
    if reverse_order:
        records.reverse()

    media = InstagramProcessor._find_image_media(
        _json_html(*records),
        "DuplicateCarousel01",
    )

    assert media == complete


@pytest.mark.parametrize(
    ("documents", "expected_count"),
    [
        (
            [
                {
                    "items": [
                        {
                            "pk": "video-media",
                            "code": "TargetPost01",
                            "media_type": 2,
                            "video_versions": [
                                {"url": "https://example.com/video.mp4"}
                            ],
                        }
                    ]
                }
            ],
            0,
        ),
        (
            [
                {
                    "pk": "first-media",
                    "code": "TargetPost01",
                    "media_type": 1,
                    "image_versions2": {"candidates": []},
                },
                {
                    "pk": "second-media",
                    "code": "TargetPost01",
                    "media_type": 8,
                    "carousel_media": [],
                },
            ],
            2,
        ),
    ],
)
def test_rejects_invalid_image_media_count(
    documents: list[object],
    expected_count: int,
):
    html = _json_html(*documents)

    with pytest.raises(
        RuntimeError,
        match=rf"Expected one Instagram image record, found {expected_count}",
    ):
        InstagramProcessor._find_image_media(
            html,
            "TargetPost01",
        )


def _image_candidate(
    name: str,
    width: int,
    height: int,
) -> dict:
    return {
        "url": (f"https://scontent-lax3-1.cdninstagram.com/{name}.jpg"),
        "width": width,
        "height": height,
    }


def test_select_image_uses_display_uri_without_candidate_dimensions():
    display_uri = "https://scontent-lax3-1.cdninstagram.com/display-original.jpg"
    media = {
        "display_uri": display_uri,
        "original_width": 2560,
        "original_height": 2560,
        "image_versions2": {
            "candidates": [
                {
                    "url": (
                        "https://scontent-lax3-1.cdninstagram.com/candidate-small.jpg"
                    )
                },
                {
                    "url": (
                        "https://scontent-lax3-1.cdninstagram.com/candidate-large.jpg"
                    )
                },
            ]
        },
    }

    selected = InstagramProcessor._select_largest_image_url(
        media,
    )

    assert selected == display_uri


def test_extract_image_urls_from_single_image_media():
    small = _image_candidate("single-small", 320, 400)
    largest = _image_candidate("single-largest", 1080, 1350)
    medium = _image_candidate("single-medium", 720, 900)
    media = {
        "media_type": 1,
        "image_versions2": {
            "candidates": [small, largest, medium],
        },
    }

    image_urls = InstagramProcessor._extract_image_urls(media)

    assert image_urls == [largest["url"]]


def test_extract_image_urls_from_carousel_in_original_order():
    first_small = _image_candidate("first-small", 320, 400)
    first_largest = _image_candidate("first-largest", 1080, 1350)
    second_largest = _image_candidate("second-largest", 1080, 1080)
    second_small = _image_candidate("second-small", 320, 320)
    media = {
        "media_type": 8,
        "carousel_media": [
            {
                "image_versions2": {
                    "candidates": [first_small, first_largest],
                },
            },
            {
                "image_versions2": {
                    "candidates": [second_largest, second_small],
                },
            },
        ],
    }

    image_urls = InstagramProcessor._extract_image_urls(media)

    assert image_urls == [
        first_largest["url"],
        second_largest["url"],
    ]


@pytest.mark.parametrize(
    ("url", "error_message"),
    [
        (
            "http://scontent-lax3-1.cdninstagram.com/image.jpg",
            "Instagram image URL is not valid HTTPS",
        ),
        (
            "/relative/image.jpg",
            "Instagram image URL is not valid HTTPS",
        ),
        (
            "https://example.com/image.jpg",
            "Instagram image URL uses an unexpected CDN host",
        ),
        (
            "https://cdninstagram.com.evil.example/image.jpg",
            "Instagram image URL uses an unexpected CDN host",
        ),
    ],
)
def test_rejects_invalid_instagram_image_url(
    url: str,
    error_message: str,
):
    media = {
        "media_type": 1,
        "image_versions2": {
            "candidates": [
                {
                    "url": url,
                    "width": 1080,
                    "height": 1350,
                }
            ],
        },
    }

    with pytest.raises(
        RuntimeError,
        match=error_message,
    ):
        InstagramProcessor._extract_image_urls(media)


def test_extract_single_image_from_target_article_src():
    target_url = _image_candidate(
        "dom-single-target",
        1080,
        1350,
    )["url"]
    avatar_url = _image_candidate(
        "dom-single-avatar",
        150,
        150,
    )["url"]
    unrelated_url = _image_candidate(
        "dom-single-unrelated",
        1080,
        1080,
    )["url"]
    html = f"""
        <article>
            <a href="/other/p/OtherPost01/"></a>
            <div class="_aagv">
                <img src="{unrelated_url}">
            </div>
        </article>
        <article>
            <a href="/tutorcircle/p/DcFzoFogOFC/"></a>
            <div class="_aagv">
                <img src="{target_url}">
            </div>
            <img src="{avatar_url}" alt="avatar">
            <h1>Target Instagram caption</h1>
        </article>
    """

    image_url, caption = InstagramProcessor._extract_single_image_from_dom(
        html,
        "DcFzoFogOFC",
    )

    assert image_url == target_url
    assert caption == "Target Instagram caption"


def test_extract_single_image_from_largest_srcset_candidate():
    small_url = _image_candidate(
        "dom-srcset-small",
        320,
        400,
    )["url"]
    largest_url = _image_candidate(
        "dom-srcset-largest",
        1080,
        1350,
    )["url"]
    medium_url = _image_candidate(
        "dom-srcset-medium",
        720,
        900,
    )["url"]
    html = f"""
        <article>
            <a href="/p/SinglePost01/"></a>
            <div class="_aagv">
                <img
                    src="{small_url}"
                    srcset="
                        {medium_url} 720w,
                        {largest_url} 1080w,
                        {small_url} 320w
                    "
                >
            </div>
            <h1>Single image caption</h1>
        </article>
    """

    image_url, caption = InstagramProcessor._extract_single_image_from_dom(
        html,
        "SinglePost01",
    )

    assert image_url == largest_url
    assert caption == "Single image caption"


def test_extract_post_data_prefers_matching_json_media():
    structured_url = _image_candidate(
        "structured-single",
        1080,
        1350,
    )["url"]
    target = {
        "pk": "structured-media",
        "code": "StructuredPost01",
        "media_type": 1,
        "image_versions2": {
            "candidates": [
                {
                    "url": structured_url,
                    "width": 1080,
                    "height": 1350,
                }
            ],
        },
        "caption": {
            "text": "Structured caption",
        },
    }
    html = (
        _json_html({"payload": target})
        + """
        <article>
            <a href="/creator/p/StructuredPost01/"></a>
            <div class="_aagv">
                <img src="https://example.com/incorrect.jpg">
            </div>
            <h1>Incorrect DOM caption</h1>
        </article>
    """
    )

    image_urls, caption = InstagramProcessor._extract_post_data(
        html,
        "StructuredPost01",
    )

    assert image_urls == [structured_url]
    assert caption == "Structured caption"


def test_extract_post_data_falls_back_to_single_image_dom():
    dom_url = _image_candidate(
        "dom-fallback",
        1080,
        1350,
    )["url"]
    html = f"""
        <article>
            <a href="/creator/p/DomFallback01/"></a>
            <div class="_aagv">
                <img src="{dom_url}">
            </div>
            <h1>DOM fallback caption</h1>
        </article>
    """

    image_urls, caption = InstagramProcessor._extract_post_data(
        html,
        "DomFallback01",
    )

    assert image_urls == [dom_url]
    assert caption


async def test_convert_builds_ordered_image_markdown_and_caption():
    first_url = _image_candidate(
        "convert-first",
        1080,
        1350,
    )["url"]
    second_url = _image_candidate(
        "convert-second",
        1080,
        1350,
    )["url"]
    downloaded_images = [
        Image(
            name="1",
            link=first_url,
            data="first-base64",
            mimetype="image/jpeg",
        ),
        Image(
            name="2",
            link=second_url,
            data="second-base64",
            mimetype="image/jpeg",
        ),
    ]
    processor = _processor()
    processor.collect_url._scrape_url = AsyncMock()
    processor._extract_post_data = Mock(
        return_value=(
            [first_url, second_url],
            "Instagram post caption",
        )
    )
    processor.get_images = AsyncMock(return_value=downloaded_images)

    result = await processor.convert(
        "<html></html>",
        "https://www.instagram.com/p/ConvertPost01/",
    )

    processor.collect_url._scrape_url.assert_not_awaited()

    processor._extract_post_data.assert_called_once_with(
        "<html></html>",
        "ConvertPost01",
    )
    processor.get_images.assert_awaited_once_with(
        [
            (first_url, "1"),
            (second_url, "2"),
        ]
    )
    assert result.title == "Instagram post caption"
    assert result.markdown == (
        f"![1]({first_url})\n\n![2]({second_url})\n\nInstagram post caption"
    )
    assert result.images == downloaded_images


def test_html_reader_registers_instagram_processor(
    monkeypatch,
):
    monkeypatch.setattr(
        "omnibox_wizard.worker.functions.html_reader.html_reader.HTMLContentExtractor",
        Mock(return_value=Mock()),
    )
    reader = HTMLReaderV2(config=Mock())

    processor = reader.get_processor(
        "",
        "https://www.instagram.com/p/DcFzoFogOFC/",
    )

    assert isinstance(processor, InstagramProcessor)


async def test_convert_rejects_partial_image_download():
    first_url = _image_candidate(
        "partial-first",
        1080,
        1350,
    )["url"]
    second_url = _image_candidate(
        "partial-second",
        1080,
        1350,
    )["url"]
    downloaded_image = Image(
        name="1",
        link=first_url,
        data="first-base64",
        mimetype="image/jpeg",
    )
    processor = _processor()
    processor._extract_post_data = Mock(
        return_value=(
            [first_url, second_url],
            "Instagram post caption",
        )
    )
    processor.get_images = AsyncMock(return_value=[downloaded_image])

    with pytest.raises(
        RuntimeError,
        match=("Expected 2 Instagram images to be downloaded, got 1"),
    ):
        await processor.convert(
            "<html></html>",
            "https://www.instagram.com/p/PartialPost01/",
        )


async def test_fetch_img_uses_proxy_and_instagram_request_config(
    monkeypatch,
):
    proxy = "http://proxy.example:8080"
    image_url = "https://scontent.example.cdninstagram.com/image.jpg?signature=secret"
    transport = Mock()
    transport_factory = Mock(return_value=transport)

    response = Mock(
        status_code=200,
        headers={"Content-Type": "image/png"},
        content=b"image",
    )
    client = Mock()
    client.get = AsyncMock(return_value=response)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    client_factory = Mock(return_value=client)

    monkeypatch.setenv("OB_SCRAPE_PROXY", proxy)
    monkeypatch.setattr(
        "omnibox_wizard.worker.functions.html_reader.processors."
        "instagram.httpx.AsyncHTTPTransport",
        transport_factory,
    )
    monkeypatch.setattr(
        "omnibox_wizard.worker.functions.html_reader.processors."
        "instagram.httpx.AsyncClient",
        client_factory,
    )

    result = await InstagramProcessor.fetch_img(image_url)

    assert result == ("image/png", "aW1hZ2U=")
    transport_factory.assert_called_once_with(
        retries=3,
        proxy=proxy,
    )

    client_kwargs = client_factory.call_args.kwargs
    assert client_kwargs["headers"] == InstagramProcessor.HEADERS
    assert client_kwargs["follow_redirects"] is True
    assert client_kwargs["transport"] is transport
    assert client_kwargs["timeout"].connect == 20.0
    assert client_kwargs["timeout"].read == 60.0
    assert client_kwargs["timeout"].write == 60.0
    assert client_kwargs["timeout"].pool == 60.0

    client.get.assert_awaited_once_with(image_url)
    response.raise_for_status.assert_called_once_with()


async def test_fetch_img_records_sanitized_http_error(
    monkeypatch,
):
    image_url = (
        "https://scontent.example.cdninstagram.com/image.jpg?signature=sensitive"
    )
    request = httpx.Request("GET", image_url)
    error = httpx.ConnectTimeout(
        "connection timed out",
        request=request,
    )
    span = Mock()
    transport = Mock()
    client = Mock()
    client.get = AsyncMock(side_effect=error)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)

    monkeypatch.delenv("OB_SCRAPE_PROXY", raising=False)
    monkeypatch.setattr(
        "omnibox_wizard.worker.functions.html_reader.processors."
        "instagram.httpx.AsyncHTTPTransport",
        Mock(return_value=transport),
    )
    monkeypatch.setattr(
        "omnibox_wizard.worker.functions.html_reader.processors."
        "instagram.httpx.AsyncClient",
        Mock(return_value=client),
    )
    monkeypatch.setattr(
        "omnibox_wizard.worker.functions.html_reader.processors."
        "instagram.trace.get_current_span",
        Mock(return_value=span),
    )

    result = await InstagramProcessor.fetch_img(image_url)

    assert result is None
    span.set_attribute.assert_any_call(
        "image.host",
        "scontent.example.cdninstagram.com",
    )
    span.set_attribute.assert_any_call("has_proxy", False)
    span.set_attribute.assert_any_call(
        "error.type",
        "ConnectTimeout",
    )
    span.record_exception.assert_not_called()

    status = span.set_status.call_args.args[0]
    assert status.status_code is trace.StatusCode.ERROR
    assert status.description == "ConnectTimeout"


async def test_convert_rescrapes_canonical_post_for_incomplete_carousel():
    shortcode = "RetryCarousel01"
    first_url = _image_candidate(
        "retry-first",
        1080,
        1350,
    )["url"]
    second_url = _image_candidate(
        "retry-second",
        1080,
        1350,
    )["url"]

    initial_html = f"""
        <article>
            <a href="/creator/p/{shortcode}/"></a>
            <div class="_aagv"><img src="{first_url}"></div>
            <div class="_aagv"><img src="{second_url}"></div>
            <h1>Incomplete DOM caption</h1>
        </article>
    """
    canonical_html = _json_html(
        {
            "pk": "retry-carousel-media",
            "code": shortcode,
            "media_type": 8,
            "caption": {
                "text": "Complete structured caption",
            },
            "carousel_media": [
                {
                    "image_versions2": {
                        "candidates": [
                            _image_candidate(
                                "retry-first",
                                1080,
                                1350,
                            )
                        ]
                    }
                },
                {
                    "image_versions2": {
                        "candidates": [
                            _image_candidate(
                                "retry-second",
                                1080,
                                1350,
                            )
                        ]
                    }
                },
            ],
        }
    )
    downloaded_images = [
        Image(
            name="1",
            link=first_url,
            data="first-base64",
            mimetype="image/jpeg",
        ),
        Image(
            name="2",
            link=second_url,
            data="second-base64",
            mimetype="image/jpeg",
        ),
    ]

    processor = _processor()
    processor.collect_url = Mock()
    processor.collect_url._scrape_url = AsyncMock(
        return_value=Mock(html=canonical_html)
    )
    processor.get_images = AsyncMock(
        return_value=downloaded_images,
    )

    result = await processor.convert(
        initial_html,
        f"https://www.instagram.com/p/{shortcode}/?img_index=1",
    )

    processor.collect_url._scrape_url.assert_awaited_once_with(
        f"https://www.instagram.com/p/{shortcode}/"
    )
    processor.get_images.assert_awaited_once_with(
        [
            (first_url, "1"),
            (second_url, "2"),
        ]
    )
    assert result.images == downloaded_images
    assert "Complete structured caption" in result.markdown
    assert "Incomplete DOM caption" not in result.markdown


@pytest.mark.parametrize(
    ("caption", "author_name", "expected_title"),
    [
        (
            "第一段正文\n\n第二段正文  包含连续空格",
            "示例作者",
            "第一段正文 第二段正文 包含连续空格",
        ),
        (
            "   ",
            "示例作者",
            "示例作者",
        ),
    ],
)
def test_build_title_from_caption_or_author(
    caption: str,
    author_name: str,
    expected_title: str,
):
    assert (
        InstagramProcessor._build_title(
            caption,
            author_name,
        )
        == expected_title
    )


@pytest.mark.parametrize(
    ("user", "expected_author"),
    [
        (
            {
                "full_name": "示例作者",
                "username": "example_user",
            },
            "示例作者",
        ),
        (
            {
                "full_name": "   ",
                "username": "example_user",
            },
            "@example_user",
        ),
    ],
)
def test_extract_author_name_prefers_full_name(
    user: dict,
    expected_author: str,
):
    media = {"user": user}

    assert InstagramProcessor._extract_author_name(media) == expected_author


async def test_convert_uses_author_name_when_caption_is_empty():
    shortcode = "AuthorFallback01"
    image_url = _image_candidate(
        "author-fallback",
        1080,
        1350,
    )["url"]
    html = _json_html(
        {
            "pk": "author-fallback-media",
            "code": shortcode,
            "media_type": 1,
            "caption": {
                "text": "   ",
            },
            "user": {
                "full_name": "示例作者",
                "username": "example_user",
            },
            "image_versions2": {
                "candidates": [
                    _image_candidate(
                        "author-fallback",
                        1080,
                        1350,
                    )
                ]
            },
        }
    )
    downloaded_image = Image(
        name="1",
        link=image_url,
        data="image-base64",
        mimetype="image/jpeg",
    )
    processor = _processor()
    processor.collect_url._scrape_url = AsyncMock()
    processor.get_images = AsyncMock(
        return_value=[downloaded_image],
    )

    result = await processor.convert(
        html,
        f"https://www.instagram.com/p/{shortcode}/",
    )

    processor.collect_url._scrape_url.assert_not_awaited()
    assert result.title == "示例作者"
