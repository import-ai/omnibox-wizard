from urllib.parse import urlparse

from bs4 import BeautifulSoup, Tag, Comment, NavigableString
from opentelemetry import trace

from omnibox_wizard.worker.entity import GeneratedContent
from omnibox_wizard.worker.functions.html_reader_processors.base import (
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

    @tracer.start_as_current_span("RedNoteProcessor.convert")
    async def convert(self, html: str, url: str) -> GeneratedContent:
        soup = BeautifulSoup(html, "html.parser")
        image_selection = soup.select('meta[name="og:image"]')
        title_selection = soup.select("div.note-content div#detail-title")
        content_selection = soup.select(
            "div.note-content div#detail-desc span.note-text"
        )

        image_links = []
        for image_tag in image_selection:
            if url := image_tag.get("content"):
                if "sns-webpic-qc.xhscdn.com" in url:
                    image_links.append(url)

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
