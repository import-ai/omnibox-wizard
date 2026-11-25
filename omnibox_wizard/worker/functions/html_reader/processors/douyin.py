import asyncio
import json
import re
from html import unescape
from urllib.parse import unquote, urlparse

from bs4 import BeautifulSoup
from wizard_common.worker.entity import GeneratedContent, Image

from omnibox_wizard.worker.functions.html_reader.processors.base import (
    HTMLReaderBaseProcessor,
)


def parse_video_detail(soup: BeautifulSoup) -> dict | None:
    script = soup.find("script", id="RENDER_DATA")
    if script is None or script.string is None:
        return None
    try:
        data = json.loads(unquote(unescape(script.string)))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None

    app = data.get("app")
    if isinstance(app, dict) and isinstance(app.get("videoDetail"), dict):
        return app["videoDetail"]
    detail = data.get("videoDetail")
    return detail if isinstance(detail, dict) else None


def _image_entries(detail: dict) -> list:
    images = detail.get("images")
    if isinstance(images, list) and images:
        return images
    video = detail.get("video")
    images = video.get("images") if isinstance(video, dict) else None
    return images if isinstance(images, list) else []


def _post_text(detail: dict, field: str) -> str:
    value = detail.get(field)
    return value.strip() if isinstance(value, str) else ""


def _image_key(src: str) -> str:
    """Strip CDN transform params so duplicates of one image collapse."""
    return urlparse(src).path.split("~")[0]


def image_panel_links(soup: BeautifulSoup) -> list[str]:
    """Return the displayed image post links in original order.

    Douyin renders the active image post inside .focusPanel and keeps video
    posts out of it, so the panel always describes what is on screen even when
    RENDER_DATA still carries a previously opened post.
    """
    panel = soup.select_one(".focusPanel")
    if panel is None:
        return []

    links: list[str] = []
    seen: set[str] = set()
    for img in panel.select('img[src*="douyinpic"]'):
        src = img.get("src")
        if not isinstance(src, str) or not src.startswith("https://"):
            continue
        key = _image_key(src)
        if key in seen:
            continue
        seen.add(key)
        links.append(src)
    return links


def has_image_post_panel(soup: BeautifulSoup) -> bool:
    return bool(image_panel_links(soup))


_ACTIVE_VIDEO_ID_RE = re.compile(r"\bvideo_(\d+)\b")


def image_post_text(soup: BeautifulSoup) -> str:
    """Read the caption of the post currently rendered in the page."""
    element = soup.select_one('[data-e2e="video-desc"]')
    if element is None:
        return ""
    text = " ".join(element.get_text(" ", strip=True).split())
    for suffix in ("展开", "收起"):
        text = text.replace(suffix, "").strip()
    return text


def active_post_id(soup: BeautifulSoup) -> str | None:
    """Read the aweme id of the item currently shown in the feed.

    Douyin marks the active slide with data-e2e="feed-active-video" and keeps
    its id in the class list, which tells which post the page is showing even
    when RENDER_DATA still describes a previously opened one.
    """
    feed = soup.find(attrs={"data-e2e": "feed-active-video"})
    if feed is None:
        return None
    match = _ACTIVE_VIDEO_ID_RE.search(" ".join(feed.get("class") or []))
    return match.group(1) if match else None


def is_active_video_playing(soup: BeautifulSoup) -> bool:
    """Whether the feed's active video container is currently visible."""
    feed = soup.find(attrs={"data-e2e": "feed-active-video"})
    if feed is None:
        return False
    return any(
        "hideXgVideo" not in (c.get("class") or [])
        for c in feed.find_all("xg-video-container")
    )


class DouyinProcessor(HTMLReaderBaseProcessor):
    def hit(self, html: str, url: str) -> bool:
        host = urlparse(url).hostname or ""
        if host != "douyin.com" and not host.endswith(".douyin.com"):
            return False
        soup = BeautifulSoup(html, "html.parser")
        if has_image_post_panel(soup):
            return True
        detail = parse_video_detail(soup)
        return bool(detail and _image_entries(detail))

    async def _download_first(self, urls: list, name: str) -> Image | None:
        for src in urls:
            if not isinstance(src, str):
                continue
            parsed = urlparse(src)
            host = parsed.hostname or ""
            if parsed.scheme != "https" or not host.endswith(".douyinpic.com"):
                continue
            images = await self.get_images([(src, name)])
            if images:
                return images[0]
        return None

    async def convert(self, html: str, url: str) -> GeneratedContent:
        soup = BeautifulSoup(html, "html.parser")
        detail = parse_video_detail(soup) or {}

        # Prefer the image panel: it always reflects the displayed post, while
        # RENDER_DATA can still describe a previously opened one.
        panel_links = image_panel_links(soup)
        if panel_links:
            url_groups: list[list] = [[link] for link in panel_links]
        else:
            url_groups = [
                entry.get("urlList") if isinstance(entry, dict) else []
                for entry in _image_entries(detail)
            ]

        downloaded = await asyncio.gather(
            *(
                self._download_first(urls, str(index))
                for index, urls in enumerate(url_groups, start=1)
            )
        )
        images = [image for image in downloaded if image is not None]

        # RENDER_DATA can describe a previously opened post, so trust it only
        # when it matches the post the page is showing right now.
        current_id = active_post_id(soup)
        detail_id = str(detail.get("awemeId") or "")
        stale = bool(panel_links) and current_id is not None and current_id != detail_id
        desc = image_post_text(soup) if stale else _post_text(detail, "desc")
        title = None if stale else (_post_text(detail, "itemTitle") or None)

        parts = [desc]
        parts.extend(f"![{image.name}]({image.link})" for image in images)
        return GeneratedContent(
            title=title,
            markdown="\n\n".join(filter(None, parts)),
            images=images or None,
        )
