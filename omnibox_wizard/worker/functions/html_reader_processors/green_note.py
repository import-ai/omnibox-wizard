from urllib.parse import urlparse

from bs4 import BeautifulSoup
from html2text import html2text

from omnibox_wizard.worker.entity import GeneratedContent
from omnibox_wizard.worker.functions.html_reader_processors.base import HTMLReaderBaseProcessor
from opentelemetry import trace

tracer = trace.get_tracer("GreenNoteProcessor")


class GreenNoteProcessor(HTMLReaderBaseProcessor):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def hit(self, html: str, url: str) -> bool:
        parsed = urlparse(url)
        if parsed.netloc == 'mp.weixin.qq.com':
            if parsed.path.startswith('/s/'):
                soup = BeautifulSoup(html, "html.parser")
                if soup.select("p#js_image_desc") or soup.select("div#js_image_content h1"):
                    return True
        return False

    @tracer.start_as_current_span("GreenNoteProcessor.convert")
    async def convert(self, html: str, url: str) -> GeneratedContent:
        soup = BeautifulSoup(html, "html.parser")
        images = soup.select("div.swiper_item_img img:not(#img_item_placeholder)")
        content = soup.find("p", attrs={"id": "js_image_desc"})
        h1 = soup.select("div#js_image_content h1")[0]

        tuple_images: list[tuple[str, str]] = []

        for img in images:
            if src := img.get("src"):
                if not any(x[0] == src for x in tuple_images):
                    tuple_images.append((src, img.get("alt", self.get_name_from_url(src))))

        title: str = h1.text
        images = await self.get_images(tuple_images)
        markdown_images: str = "\n\n".join([f"![{i + 1}]({image.link})" for i, image in enumerate(images)])
        markdown = markdown_images + "\n\n" + html2text(content.prettify())
        return GeneratedContent(title=title, markdown=markdown, images=images or None)
