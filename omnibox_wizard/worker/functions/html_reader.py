import json as jsonlib
import re
from functools import partial
from urllib.parse import urlparse

from bs4 import BeautifulSoup, Tag, Comment
from html2text import html2text
from lxml.etree import tounicode
from opentelemetry import trace
from readability import Document
from readability.cleaners import clean_attributes

from omnibox_wizard.common.trace_info import TraceInfo
from omnibox_wizard.worker.agent.html_content_extractor import HTMLContentExtractor
from omnibox_wizard.worker.agent.html_title_extractor import HTMLTitleExtractor
from omnibox_wizard.worker.config import WorkerConfig
from omnibox_wizard.worker.entity import Task
from omnibox_wizard.worker.functions.base_function import BaseFunction

json_dumps = partial(jsonlib.dumps, separators=(",", ":"), ensure_ascii=False)
tracer = trace.get_tracer(__name__)


class HTMLReaderV2(BaseFunction):
    SPACE_PATTERN: re.Pattern = re.compile(r"\s{2,}")
    CONTENT_SELECTOR = {
        "github.com": {
            "name": "article",
            "class_": "markdown-body"
        },
        "medium.com": {
            "name": "article"
        },
        "mp.weixin.qq.com": {
            "name": "div",
            "class_": "rich_media_content"
        },
        "news.qq.com": {
            "name": "div",
            "class_": "content-article"
        },
        "zhuanlan.zhihu.com": {
            "name": "article"
        },
        "www.163.com": {
            "name": "div",
            "class_": "post_body"
        },
        "www.xiaohongshu.com": {
            "name": "div",
            "class_": "note-content"
        },
        "x.com": {
            "name": "div",
            "attrs": {"data-testid": "tweetText"}
        }
    }

    def __init__(self, config: WorkerConfig):
        self.html_title_extractor = HTMLTitleExtractor(config.grimoire.openai.get_config("mini"))
        self.html_content_extractor = HTMLContentExtractor(config.grimoire.openai.get_config("mini"))

    @classmethod
    def content_selector(cls, domain: str, soup: BeautifulSoup) -> Tag:
        if selector := cls.CONTENT_SELECTOR.get(domain, None):
            if content := soup.find(**selector):
                return content
        return soup

    def clean_html(self, html: str, *, clean_svg: bool = False, clean_base64: bool = False,
                   compress: bool = False, remove_empty_tag: bool = False, remove_atts: bool = False,
                   allowed_attrs: set | None = None) -> str:
        soup = BeautifulSoup(html, 'html.parser')

        # Remove script, style, meta, and link tags
        for tag_name in ['script', 'style', 'meta', 'link']:
            for tag in soup.find_all(tag_name):
                tag.decompose()

        # Remove comments
        for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
            comment.extract()

        # Clean SVG tags if clean_svg is True
        if clean_svg:
            for svg_tag in soup.find_all('svg'):
                # Replace the contents of the svg tag with a placeholder
                svg_tag.clear()

        # Clean base64 images if clean_base64 is True
        if clean_base64:
            for img_tag in soup.find_all('img'):
                src = img_tag.get('src', '')
                if src.startswith('data:image/') and 'base64,' in src:
                    img_tag['src'] = '#'

        # Remove attributes if remove_atts is True
        if remove_atts and not allowed_attrs:
            allowed_attrs = {"src", "alt", "class", "hidden", "style"}

        # Remove attributes if allowed_attrs is not None
        if allowed_attrs:
            for tag in soup.find_all():
                tag.attrs = {k: v for k, v in tag.attrs.items() if k in allowed_attrs}

        # Remove empty tags if remove_empty_tag is True
        if remove_empty_tag:
            for tag in soup.find_all():
                if (tag.name and tag.name.lower() == "img") or tag.find("img") is not None:
                    continue
                if not tag.get_text(strip=True):
                    tag.decompose()

        # Convert the modified soup back to a string
        cleaned_html = str(soup)

        # Compress whitespace if compress is True
        if compress:
            # Replace multiple whitespace characters with a single space
            cleaned_html = self.SPACE_PATTERN.sub(' ', cleaned_html).strip()

        return cleaned_html

    @tracer.start_as_current_span("HTMLReaderV2.run")
    async def run(self, task: Task, trace_info: TraceInfo) -> dict:
        input_dict = task.input
        html = input_dict["html"]
        url = input_dict["url"]

        domain: str = urlparse(url).netloc
        trace_info = trace_info.bind(domain=domain)

        result_dict: dict = await self.convert(domain, html, trace_info)
        trace_info.info({k: v for k, v in result_dict.items() if k != "markdown"})
        return result_dict

    async def convert(self, domain: str, html: str, trace_info: TraceInfo):
        span = trace.get_current_span()
        html_doc = Document(html)

        raw_title: str = html_doc.title()
        if domain in self.CONTENT_SELECTOR:
            with tracer.start_as_current_span("HTMLReaderV2.content_selector"):
                selected_html = self.content_selector(domain, BeautifulSoup(html, "html.parser")).prettify()
                cleaned_html = clean_attributes(tounicode(Document(selected_html)._html(True), method="html"))
                markdown = html2text(cleaned_html).strip()
        else:
            html_summary: str = html_doc.summary().strip()
            markdown: str = html2text(html_summary).strip()

            log_body: dict = {
                "len(html)": len(html),
                "len(html_summary)": len(html_summary),
                "compress_rate": f"{len(html_summary) * 100 / len(html): .2f}%",
                "len(markdown)": len(markdown),
            }
            trace_info.info(log_body)
            span.set_attributes(log_body)

        if not markdown:
            with tracer.start_as_current_span("HTMLReaderV2.llm_extract_content"):
                cleaned_html: str = clean_attributes(tounicode(Document(html)._html(True), method="html"))
                cleaned_html: str = self.clean_html(
                    cleaned_html, clean_svg=True, clean_base64=True,
                    remove_atts=True, compress=True, remove_empty_tag=True,
                )
                markdown = await self.html_content_extractor.ainvoke({"html": cleaned_html}, trace_info)

        snippet: str = "\n".join(list(filter(bool, markdown.splitlines()))[:3])

        with tracer.start_as_current_span("HTMLReaderV2.llm_extract_title"):
            title: str = (
                await self.html_title_extractor.ainvoke({
                    "title": raw_title, "snippet": snippet
                }, trace_info)
            ).title

        return {"title": title, "markdown": markdown}
