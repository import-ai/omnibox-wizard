from urllib.parse import urlparse, urlsplit, urlunsplit

from bs4 import BeautifulSoup, Tag
from html2text import html2text
from opentelemetry import trace

from omnibox_wizard.worker.entity import GeneratedContent
from omnibox_wizard.worker.functions.html_reader_processors.base import (
    HTMLReaderBaseProcessor,
)

tracer = trace.get_tracer("OKJikeProcessor")


class OKJikeWebProcessor(HTMLReaderBaseProcessor):
    def hit(self, html: str, url: str) -> bool:
        parsed = urlparse(url)
        if parsed.netloc == "web.okjike.com":
            if parsed.path.startswith("/u/") and "/post/" in parsed.path:
                return True
        return False

    @tracer.start_as_current_span("OKJikeProcessor.get_body")
    def get_body(self, html: str, url: str) -> Tag | None:
        soup = BeautifulSoup(html, "html.parser")
        parsed = urlparse(url)
        user_id = parsed.path.split("/u/")[1].split("/post/")[0]
        if user_link_dom := soup.find("a", attrs={"href": f"/u/{user_id}"}):
            for p in user_link_dom.parents:
                if header := p.find("header"):
                    return header.next_sibling
        return None

    @classmethod
    def remove_query_params(cls, url: str) -> str:
        parts = urlsplit(url)
        clean_url = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
        return clean_url

    @tracer.start_as_current_span("OKJikeProcessor.convert")
    async def convert(self, html: str, url: str) -> GeneratedContent:
        body: Tag = self.get_body(html, url)
        children: list[Tag] = list(body.children)
        content: Tag = children[0]
        if len(children) == 3:
            images_dom = children[1]
            image_selection: list[Tag] = images_dom.select("img")
            for img in image_selection:
                img["src"] = self.remove_query_params(img["src"])
            images = await self.img_selection_to_image(image_selection)
        else:
            images = []
        markdown: str = "\n\n".join(
            [f"![{i + 1}]({image.link})" for i, image in enumerate(images)]
        )
        if content:
            content_with_br: str = str(next(content.children)).replace("\n", "<br>\n")
            markdown = html2text(content_with_br, bodywidth=0) + "\n\n" + markdown
        title: str = next(filter(lambda x: bool(x.strip()), markdown.split("\n")))
        return GeneratedContent(title=title, markdown=markdown, images=images or None)
