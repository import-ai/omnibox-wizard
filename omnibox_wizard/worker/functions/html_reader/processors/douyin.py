import asyncio
import json
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


class DouyinProcessor(HTMLReaderBaseProcessor):
    def hit(self, html: str, url: str) -> bool:
        host = urlparse(url).hostname or ""
        if host != "douyin.com" and not host.endswith(".douyin.com"):
            return False
        detail = parse_video_detail(BeautifulSoup(html, "html.parser"))
        return bool(detail and _image_entries(detail))

    async def _download_image(self, entry: object, name: str) -> Image | None:
        urls = entry.get("urlList") if isinstance(entry, dict) else None
        if not isinstance(urls, list):
            return None

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
        detail = parse_video_detail(BeautifulSoup(html, "html.parser")) or {}
        downloaded = await asyncio.gather(
            *(
                self._download_image(entry, str(index))
                for index, entry in enumerate(_image_entries(detail), start=1)
            )
        )
        images = [image for image in downloaded if image is not None]
        parts = [_post_text(detail, "desc")]
        parts.extend(f"![{image.name}]({image.link})" for image in images)
        return GeneratedContent(
            title=_post_text(detail, "itemTitle") or None,
            markdown="\n\n".join(filter(None, parts)),
            images=images or None,
        )
