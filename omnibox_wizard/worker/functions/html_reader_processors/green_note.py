from urllib.parse import urlparse

from bs4 import BeautifulSoup
from html2text import html2text
from opentelemetry import trace

from omnibox_wizard.worker.entity import GeneratedContent
from omnibox_wizard.worker.functions.html_reader_processors.base import HTMLReaderBaseProcessor

tracer = trace.get_tracer("GreenNoteProcessor")


class GreenNoteProcessor(HTMLReaderBaseProcessor):
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
        image_selection = soup.select("div.swiper_item_img img:not(#img_item_placeholder)")
        content = soup.find("p", attrs={"id": "js_image_desc"})
        h1_selection = soup.select("div#js_image_content h1")
        images = await self.img_selection_to_image(image_selection)

        if h1_selection:
            title: str = h1_selection[0].text.strip()
        else:
            title = "微信图文"
        markdown: str = "\n\n".join([f"![{i + 1}]({image.link})" for i, image in enumerate(images)])
        if content:
            markdown = markdown + "\n\n" + html2text(content.prettify())
        return GeneratedContent(title=title, markdown=markdown, images=images or None)
