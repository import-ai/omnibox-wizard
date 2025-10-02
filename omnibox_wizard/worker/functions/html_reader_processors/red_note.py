from urllib.parse import urlparse

from bs4 import BeautifulSoup, Tag, Comment, NavigableString
from opentelemetry import trace

from omnibox_wizard.worker.entity import GeneratedContent
from omnibox_wizard.worker.functions.html_reader_processors.base import HTMLReaderBaseProcessor

tracer = trace.get_tracer("RedNoteProcessor")


class RedNoteProcessor(HTMLReaderBaseProcessor):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def hit(self, html: str, url: str) -> bool:
        parsed = urlparse(url)
        if parsed.netloc == 'www.xiaohongshu.com':
            if parsed.path.startswith('/explore/'):
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
                if child.name == 'span':
                    if text := child.get_text(strip=False).strip():
                        markdown_parts.append(text)

                elif child.name == 'img' and 'note-content-emoji' in child.get('class', []):
                    src = child.get('src', '')
                    markdown_parts.append(f"![emoji]({src})")

                elif child.name == 'a' and 'tag' in child.get('class', []):
                    tag_text = child.get_text(strip=True)
                    href = 'https://www.xiaohongshu.com' + child.get('href', '')
                    markdown_parts.append(f"[{tag_text}]({href})")
            else:
                markdown_parts.append(child.get_text(strip=True))

        markdown = ' '.join(markdown_parts)
        return markdown.strip()

    @tracer.start_as_current_span("GreenNoteProcessor.convert")
    async def convert(self, html: str, url: str) -> GeneratedContent:
        soup = BeautifulSoup(html, "html.parser")
        images = soup.select("img.note-slider-img")
        title = soup.select("div.note-content div#detail-title")[0].text
        content = soup.select("div.note-content div#detail-desc span.note-text")[0]

        tuple_images: list[tuple[str, str]] = []

        for img in images:
            if src := img.get("src"):
                if not any(x[0] == src for x in tuple_images):
                    tuple_images.append((src, img.get("alt", self.get_name_from_url(src))))

        images = await self.get_images(tuple_images)
        markdown: str = "\n\n".join([f"![{i + 1}]({image.link})" for i, image in enumerate(images)])
        if content:
            markdown = markdown + "\n\n" + self.content_to_md(content)
        return GeneratedContent(title=title, markdown=markdown, images=images or None)
