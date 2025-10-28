from urllib.parse import urlparse,urlsplit, urlunsplit

from bs4 import BeautifulSoup, Tag
from html2text import html2text
from opentelemetry import trace

from omnibox_wizard.worker.entity import GeneratedContent
from omnibox_wizard.worker.functions.html_reader_processors.base import HTMLReaderBaseProcessor

tracer = trace.get_tracer("OKJikeMProcessor")


class OKJikeMProcessor(HTMLReaderBaseProcessor):

    def hit(self, html: str, url: str) -> bool:
        parsed = urlparse(url)
        if parsed.netloc == 'm.okjike.com':
            if parsed.path.startswith('/originalPosts/'):
                return True
        return False

    @classmethod
    def remove_query_params(cls, url: str) -> str:
        parts = urlsplit(url)
        clean_url = urlunsplit((parts.scheme, parts.netloc, parts.path, '', ''))
        return clean_url

    @tracer.start_as_current_span("OKJikeMProcessor.convert")
    async def convert(self, html: str, url: str) -> GeneratedContent:
        soup = BeautifulSoup(html, "html.parser")
        content: Tag = soup.select_one('div.post-page div.text')
        images_dom: Tag | None = content.next_sibling
        if images_dom:
            image_selection: list[Tag] = images_dom.select("img")
            for img in image_selection:
                img["src"] = self.remove_query_params(img["src"])
            images = await self.img_selection_to_image(image_selection)
        else:
            images = []
        markdown: str = "\n\n".join([f"![{i + 1}]({image.link})" for i, image in enumerate(images)])
        if content:
            markdown = html2text(str(content), bodywidth=0) + "\n\n" + markdown
        title: str = next(filter(lambda x: bool(x.strip()), markdown.split("\n")))
        return GeneratedContent(title=title, markdown=markdown, images=images or None)
