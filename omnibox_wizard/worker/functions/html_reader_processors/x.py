from urllib.parse import urlparse

from bs4 import BeautifulSoup, Tag
from html2text import html2text
from opentelemetry import trace

from omnibox_wizard.worker.entity import GeneratedContent, Image
from omnibox_wizard.worker.functions.html_reader_processors.base import (
    HTMLReaderBaseProcessor,
)

tracer = trace.get_tracer("XProcessor")


class XProcessor(HTMLReaderBaseProcessor):
    def hit(self, html: str, url: str) -> bool:
        parsed = urlparse(url)
        if parsed.netloc == "x.com":
            if "/status/" in parsed.path:
                return True
        return False

    @tracer.start_as_current_span("XProcessor.convert")
    async def convert(self, html: str, url: str) -> GeneratedContent:
        soup = BeautifulSoup(html, "html.parser")
        content: Tag = soup.select_one("div[data-testid=tweetText]")
        images: list[Image] = []
        images_dom: Tag | None = next(
            next(content.parent.parent.next_sibling.children).children
        )
        if images_dom:
            image_selection: list[Tag] = images_dom.select("img")
            for image_tag in image_selection:
                if src := image_tag.get("src"):
                    images.append(
                        Image.model_validate(
                            {
                                "name": image_tag.get("alt", src),
                                "link": src,
                                "data": "",
                                "mimetype": "",
                            }
                        )
                    )

        markdown: str = "\n\n".join(
            [
                f"![{image.name or (i + 1)}]({image.link})"
                for i, image in enumerate(images)
            ]
        )
        if content:
            content_with_br: str = str(next(content.children)).replace("\n", "<br>\n")
            markdown = html2text(content_with_br, bodywidth=0) + "\n\n" + markdown
            markdown = "\n".join(map(lambda x: x.strip(), markdown.split("\n")))
        title: str = next(filter(lambda x: bool(x.strip()), markdown.split("\n")))
        return GeneratedContent(title=title, markdown=markdown, images=None)
