import re
import json
from collections.abc import Iterator
from urllib.parse import urlparse

from bs4 import BeautifulSoup, Tag
from wizard_common.worker.entity import GeneratedContent

from omnibox_wizard.worker.functions.html_reader.processors.base import (
    HTMLReaderBaseProcessor,
)


class _InstagramImageMediaNotFoundError(RuntimeError):
    pass


class InstagramProcessor(HTMLReaderBaseProcessor):
    POST_PATH_PATTERN: re.Pattern[str] = re.compile(r"/p/([A-Za-z0-9_-]+)/?")
    ARTICLE_POST_PATH_PATTERN: re.Pattern[str] = re.compile(
        r"/(?:[^/]+/)?p/([A-Za-z0-9_-]+)/?"
    )

    def hit(self, html: str, url: str) -> bool:
        try:
            self._extract_shortcode(url)
        except RuntimeError:
            return False
        return True

    @classmethod
    def _extract_shortcode(cls, url: str) -> str:
        parsed = urlparse(url)

        if parsed.scheme != "https" or parsed.netloc.lower() != "www.instagram.com":
            raise RuntimeError("Unsupported Instagram post URL")

        match = cls.POST_PATH_PATTERN.fullmatch(parsed.path)
        if not match:
            raise RuntimeError("Unsupported Instagram post URL")

        return match.group(1)

    @staticmethod
    def _parse_json_documents(html: str) -> list[object]:
        soup = BeautifulSoup(html, "html.parser")
        documents: list[object] = []

        for index, script in enumerate(soup.select('script[type="application/json"]')):
            raw_document = script.string or script.get_text() or ""
            if not raw_document:
                continue

            try:
                documents.append(json.loads(raw_document))
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    f"Instagram JSON script {index} is malformed"
                ) from exc

        return documents

    @classmethod
    def _iter_objects(
        cls,
        value: object,
    ) -> Iterator[dict]:
        if isinstance(value, dict):
            yield value
            for child in value.values():
                yield from cls._iter_objects(child)
        elif isinstance(value, list):
            for child in value:
                yield from cls._iter_objects(child)

    @classmethod
    def _find_image_media(
        cls,
        html: str,
        shortcode: str,
    ) -> dict:
        matches: dict[str, dict] = {}

        for document in cls._parse_json_documents(html):
            for candidate in cls._iter_objects(document):
                if candidate.get("code") != shortcode:
                    continue
                if candidate.get("media_type") not in {1, 8}:
                    continue

                media_id = candidate.get("pk") or candidate.get("id")
                if not media_id:
                    raise RuntimeError(
                        "Matching Instagram image has no stable media ID"
                    )

                matches[str(media_id)] = candidate

        if not matches:
            raise _InstagramImageMediaNotFoundError(
                "Expected one Instagram image record, found 0"
            )

        if len(matches) != 1:
            raise RuntimeError(
                f"Expected one Instagram image record, found {len(matches)}"
            )

        return next(iter(matches.values()))

    @staticmethod
    def _validate_image_url(image_url: str) -> str:
        parsed = urlparse(image_url)

        if parsed.scheme != "https" or not parsed.hostname:
            raise RuntimeError("Instagram image URL is not valid HTTPS")

        hostname = parsed.hostname.lower()
        if hostname != "cdninstagram.com" and not hostname.endswith(
            ".cdninstagram.com"
        ):
            raise RuntimeError("Instagram image URL uses an unexpected CDN host")

        return image_url

    @staticmethod
    def _select_largest_image_url(media: dict) -> str:
        candidates = media.get("image_versions2", {}).get("candidates", [])
        valid_candidates: list[dict] = []

        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue

            url = candidate.get("url")
            width = candidate.get("width")
            height = candidate.get("height")

            if not isinstance(url, str) or not url:
                continue
            if not isinstance(width, (int, float)) or width <= 0:
                continue
            if not isinstance(height, (int, float)) or height <= 0:
                continue

            valid_candidates.append(candidate)

        if not valid_candidates:
            raise RuntimeError("Instagram image has no valid candidates")

        selected = max(
            valid_candidates,
            key=lambda candidate: (
                candidate["width"] * candidate["height"],
                candidate["width"],
                candidate["height"],
            ),
        )
        return selected["url"]

    @classmethod
    def _extract_image_urls(
        cls,
        media: dict,
    ) -> list[str]:
        media_type = media.get("media_type")

        if media_type == 1:
            image_items = [media]
        elif media_type == 8:
            image_items = media.get("carousel_media")
            if not isinstance(image_items, list) or not image_items:
                raise RuntimeError("Instagram carousel has no image items")
        else:
            raise RuntimeError("Unsupported Instagram image media type")

        image_urls: list[str] = []

        for image_item in image_items:
            if not isinstance(image_item, dict):
                raise RuntimeError("Instagram image item is malformed")
            if image_item.get("video_versions"):
                raise RuntimeError("Instagram mixed-media carousel is unsupported")

            selected_url = cls._select_largest_image_url(image_item)
            image_urls.append(cls._validate_image_url(selected_url))

        return image_urls

    @classmethod
    def _find_target_article(
        cls,
        soup: BeautifulSoup,
        shortcode: str,
    ) -> Tag:
        target_articles: list[Tag] = []

        for article in soup.select("article"):
            for link in article.select("a[href]"):
                href = link.get("href")
                if not isinstance(href, str):
                    continue

                path = urlparse(href).path
                match = cls.ARTICLE_POST_PATH_PATTERN.fullmatch(path)
                if match and match.group(1) == shortcode:
                    target_articles.append(article)
                    break

        if len(target_articles) != 1:
            raise RuntimeError(
                f"Expected one Instagram target article, found {len(target_articles)}"
            )

        return target_articles[0]

    @staticmethod
    def _select_largest_srcset_url(
        srcset: str,
    ) -> str | None:
        candidates = [
            (url, int(width))
            for url, width in re.findall(
                r"(\S+)\s+(\d+)w(?:\s*,\s*|\s*$)",
                srcset,
            )
        ]
        if not candidates:
            return None

        return max(
            candidates,
            key=lambda candidate: candidate[1],
        )[0]

    @classmethod
    def _extract_single_image_from_dom(
        cls,
        html: str,
        shortcode: str,
    ) -> tuple[str, str]:
        soup = BeautifulSoup(html, "html.parser")
        article = cls._find_target_article(
            soup,
            shortcode,
        )

        if article.select_one("video"):
            raise RuntimeError("Instagram target article contains video")

        image_tags = article.select("div._aagv img")
        if len(image_tags) != 1:
            raise RuntimeError(
                f"Expected one Instagram article image, found {len(image_tags)}"
            )

        image_tag = image_tags[0]
        srcset = image_tag.get("srcset", "")
        image_url = None

        if isinstance(srcset, str) and srcset:
            image_url = cls._select_largest_srcset_url(srcset)

        if not image_url:
            src = image_tag.get("src")
            if isinstance(src, str) and src:
                image_url = src

        if not image_url:
            raise RuntimeError("Instagram article image has no URL")

        caption_tag = article.select_one("h1")
        caption = caption_tag.get_text(" ", strip=True) if caption_tag else ""

        return cls._validate_image_url(image_url), caption

    @classmethod
    def _extract_post_data(
        cls,
        html: str,
        shortcode: str,
    ) -> tuple[list[str], str]:
        try:
            media = cls._find_image_media(
                html,
                shortcode,
            )
        except _InstagramImageMediaNotFoundError:
            image_url, caption = cls._extract_single_image_from_dom(
                html,
                shortcode,
            )
            return [image_url], caption

        caption_data = media.get("caption")
        caption = ""

        if isinstance(caption_data, dict):
            caption_text = caption_data.get("text")
            if isinstance(caption_text, str):
                caption = caption_text.strip()

        return cls._extract_image_urls(media), caption

    async def convert(
        self,
        html: str,
        url: str,
    ) -> GeneratedContent:
        shortcode = self._extract_shortcode(url)
        image_urls, caption = self._extract_post_data(
            html,
            shortcode,
        )

        images = await self.get_images(
            [
                (image_url, str(index))
                for index, image_url in enumerate(
                    image_urls,
                    start=1,
                )
            ]
        )

        if len(images) != len(image_urls):
            raise RuntimeError(
                f"Expected {len(image_urls)} Instagram images "
                f"to be downloaded, got {len(images)}"
            )

        markdown_parts = [f"![{image.name}]({image.link})" for image in images]
        if caption:
            markdown_parts.append(caption)

        return GeneratedContent(
            title=None,
            markdown="\n\n".join(markdown_parts),
            images=images or None,
        )
