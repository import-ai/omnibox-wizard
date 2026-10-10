import json
import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup, Tag, Comment, NavigableString
from opentelemetry import trace

from wizard_common.worker.entity import GeneratedContent
from omnibox_wizard.worker.functions.html_reader.processors.base import (
    HTMLReaderBaseProcessor,
)

tracer = trace.get_tracer("RedNoteProcessor")

_XHS_INITIAL_STATE_RE = re.compile(
    r"window\.__INITIAL_STATE__\s*=\s*(\{.*?\});?\s*</script>",
    re.S,
)


class RedNoteProcessor(HTMLReaderBaseProcessor):
    def hit(self, html: str, url: str) -> bool:
        parsed = urlparse(url)
        if parsed.netloc == "www.xiaohongshu.com":
            if parsed.path.startswith("/explore/") or parsed.path.startswith(
                "/discovery/"
            ):
                return True
        return False

    @classmethod
    def content_to_md(cls, content: Tag) -> str:
        markdown_parts = []

        for child in content.children:
            if isinstance(child, Comment):
                continue

            if isinstance(child, NavigableString):
                if text := str(child).strip():
                    markdown_parts.append(text)
                continue

            if isinstance(child, Tag):
                if child.name == "span":
                    if text := child.get_text(strip=False).strip():
                        markdown_parts.append(text)

                elif child.name == "img" and "note-content-emoji" in child.get(
                    "class", []
                ):
                    src = child.get("src", "")
                    if src.startswith(
                        "https://picasso-static.xiaohongshu.com/fe-platform/"
                    ):
                        markdown_parts.append(
                            f'<img src="{src}" width="16" height="16" alt="emoji">'
                        )
                    else:
                        markdown_parts.append(f"![emoji]({src})")

                elif child.name == "a" and "tag" in child.get("class", []):
                    tag_text = child.get_text(strip=True)
                    href = "https://www.xiaohongshu.com" + child.get("href", "")
                    markdown_parts.append(f"[{tag_text}]({href})")
            else:
                markdown_parts.append(child.get_text(strip=True))

        markdown = " ".join(markdown_parts)
        return markdown.strip()

    @classmethod
    def normalize_image_key(cls, src: str) -> str:
        return src.replace("http://", "https://").split("!")[0]

    @classmethod
    def extract_structured_image_links(cls, soup: BeautifulSoup) -> list[str]:
        image_links = []
        seen_image_keys = set()

        for script in soup.select('script[type="application/ld+json"]'):
            text = script.string or script.get_text() or ""
            if not text:
                continue

            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                continue

            items = data if isinstance(data, list) else [data]
            for item in items:
                if not isinstance(item, dict):
                    continue
                if item.get("@type") != "Article":
                    continue

                images = item.get("image") or []
                if isinstance(images, str):
                    images = [images]

                for src in images:
                    if not isinstance(src, str):
                        continue
                    if "sns-webpic-qc.xhscdn.com" not in src:
                        continue

                    image_key = cls.normalize_image_key(src)
                    if image_key in seen_image_keys:
                        continue

                    seen_image_keys.add(image_key)
                    image_links.append(src)

        return image_links

    @classmethod
    def extract_note_image_links(cls, soup: BeautifulSoup) -> list[str]:
        image_links = []
        seen_image_keys = set()

        image_selection = soup.select(
            "div.note-container div.xhs-slider-container div.note-slider-img img"
        )

        for image_tag in image_selection:
            src = image_tag.get("src", "")
            if "sns-webpic-qc.xhscdn.com" not in src:
                continue

            image_key = cls.normalize_image_key(src)
            if image_key in seen_image_keys:
                continue

            seen_image_keys.add(image_key)
            image_links.append(src)

        return image_links

    @classmethod
    def extract_og_image_links(cls, soup: BeautifulSoup) -> list[str]:
        image_links = []
        seen_image_keys = set()

        image_selection = soup.select('meta[property="og:image"]')

        for image_tag in image_selection:
            src = image_tag.get("content", "")
            if "sns-webpic-qc.xhscdn.com" not in src:
                continue

            image_key = cls.normalize_image_key(src)
            if image_key in seen_image_keys:
                continue

            seen_image_keys.add(image_key)
            image_links.append(src)

        return image_links

    @classmethod
    def extract_note_data(cls, html: str) -> dict | None:
        """Parse mobile/desktop SSR note payload from __INITIAL_STATE__."""
        match = _XHS_INITIAL_STATE_RE.search(html or "")
        if not match:
            return None

        raw = match.group(1).replace("undefined", "null").replace("void 0", "null")
        try:
            state = json.loads(raw)
            note = state["noteData"]["data"]["noteData"]
        except (json.JSONDecodeError, KeyError, TypeError, AttributeError):
            return None

        return note if isinstance(note, dict) else None

    @classmethod
    def extract_note_data_image_links(cls, note: dict) -> list[str]:
        image_links = []
        seen_image_keys = set()

        for item in note.get("imageList") or []:
            if not isinstance(item, dict):
                continue
            src = item.get("url")
            if not isinstance(src, str):
                continue
            if "sns-webpic-qc.xhscdn.com" not in src:
                continue

            image_key = cls.normalize_image_key(src)
            if image_key in seen_image_keys:
                continue

            seen_image_keys.add(image_key)
            image_links.append(src)

        return image_links

    @classmethod
    def desktop_extract(
        cls, soup: BeautifulSoup
    ) -> tuple[str | None, str, list[str]]:
        title_selection = soup.select("div.note-content div#detail-title")
        content_selection = soup.select(
            "div.note-content div#detail-desc span.note-text"
        )

        image_links = cls.extract_structured_image_links(soup)
        if not image_links:
            image_links = cls.extract_note_image_links(soup)
        if not image_links:
            image_links = cls.extract_og_image_links(soup)

        title = title_selection[0].text.strip() if title_selection else None
        content_md = (
            cls.content_to_md(content_selection[0]) if content_selection else ""
        )
        return title, content_md, image_links

    @classmethod
    def note_data_extract(cls, html: str) -> tuple[str | None, str, list[str]] | None:
        note = cls.extract_note_data(html)
        if not note:
            return None

        title = note.get("title")
        if isinstance(title, str):
            title = title.strip() or None
        else:
            title = None

        desc = note.get("desc")
        content_md = desc.strip() if isinstance(desc, str) else ""
        image_links = cls.extract_note_data_image_links(note)
        return title, content_md, image_links

    @tracer.start_as_current_span("RedNoteProcessor.convert")
    async def convert(self, html: str, url: str) -> GeneratedContent:
        soup = BeautifulSoup(html, "html.parser")
        title, content_md, image_links = self.desktop_extract(soup)

        # Mobile pages usually lack desktop note-content DOM; fall back to noteData.
        if not title and not content_md and not image_links:
            note_data_result = self.note_data_extract(html)
            if note_data_result:
                title, content_md, image_links = note_data_result

        images = await self.get_images(
            [(src, str(i + 1)) for i, src in enumerate(image_links)]
        )

        markdown: str = "\n\n".join(
            [f"![{image.name}]({image.link})" for image in images]
        )
        if content_md:
            markdown = markdown + "\n\n" + content_md if markdown else content_md
        return GeneratedContent(title=title, markdown=markdown, images=images or None)
