from urllib.parse import urlparse

from bs4 import BeautifulSoup
from html2text import html2text
from opentelemetry import trace

from omnibox_wizard.worker.entity import GeneratedContent
from omnibox_wizard.worker.functions.html_reader.processors.base import (
    HTMLReaderBaseProcessor,
)

tracer = trace.get_tracer("GreenNoticeProcessor")


class GreenNoticeProcessor(HTMLReaderBaseProcessor):
    def hit(self, html: str, url: str) -> bool:
        parsed = urlparse(url)
        if parsed.netloc == "mp.weixin.qq.com":
            if parsed.path.startswith("/s"):
                soup = BeautifulSoup(html, "html.parser")
                if soup.select("p#js_text_desc"):
                    return True
        return False

    @tracer.start_as_current_span("GreenNoticeProcessor.convert")
    async def convert(self, html: str, url: str) -> GeneratedContent:
        soup = BeautifulSoup(html, "html.parser")
        content = soup.find("p", attrs={"id": "js_text_desc"})
        markdown = html2text(content.prettify())
        title: str = next(filter(lambda x: bool(x.strip()), markdown.split("\n")))
        return GeneratedContent(title=title, markdown=markdown, images=None)
