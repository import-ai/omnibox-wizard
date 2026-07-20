from urllib.parse import urlparse

from bs4 import BeautifulSoup, Tag, Comment, NavigableString
from opentelemetry import trace

from wizard_common.worker.entity import GeneratedContent
from omnibox_wizard.worker.functions.html_reader.processors.base import (
    HTMLReaderBaseProcessor,
)

tracer = trace.get_tracer("RedNoteProcessor")


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

    @tracer.start_as_current_span("RedNoteProcessor.convert")
    async def convert(self, html: str, url: str) -> GeneratedContent:
        soup = BeautifulSoup(html, "html.parser")
        title_selection = soup.select("div.note-content div#detail-title")
        content_selection = soup.select(
            "div.note-content div#detail-desc span.note-text"
        )

        image_links = self.extract_note_image_links(soup)
        if not image_links:
            image_links = self.extract_og_image_links(soup)

        images = await self.get_images(
            [(src, str(i + 1)) for i, src in enumerate(image_links)]
        )

        markdown: str = "\n\n".join(
            [f"![{image.name}]({image.link})" for image in images]
        )
        if content_selection:
            markdown = markdown + "\n\n" + self.content_to_md(content_selection[0])
        title: str = title_selection[0].text.strip() if title_selection else None
        return GeneratedContent(title=title, markdown=markdown, images=images or None)
