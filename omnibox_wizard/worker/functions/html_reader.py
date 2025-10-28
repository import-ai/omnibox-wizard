import asyncio
import json as jsonlib
import re
from functools import partial
from urllib.parse import urlparse

import htmlmin
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
from omnibox_wizard.worker.entity import Task, Image, GeneratedContent
from omnibox_wizard.worker.functions.base_function import BaseFunction
from omnibox_wizard.worker.functions.html_reader_processors.base import HTMLReaderBaseProcessor
from omnibox_wizard.worker.functions.html_reader_processors.green_note import GreenNoteProcessor
from omnibox_wizard.worker.functions.html_reader_processors.red_note import RedNoteProcessor

json_dumps = partial(jsonlib.dumps, separators=(",", ":"), ensure_ascii=False)
tracer = trace.get_tracer("HTMLReaderV2")


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
        "x.com": {
            "name": "div",
            "attrs": {"data-testid": "tweetText"}
        },
        "www.reddit.com": {
            "name": "shreddit-post-text-body"
        }
    }

    def __init__(self, config: WorkerConfig):
        self.html_title_extractor = HTMLTitleExtractor(config.grimoire.openai.get_config("mini"))
        self.html_content_extractor = HTMLContentExtractor(config.grimoire.openai.get_config("mini"))
        self.processors: list[HTMLReaderBaseProcessor] = [
            GreenNoteProcessor(config=config), RedNoteProcessor(config=config)
        ]

    @classmethod
    def content_selector(cls, domain: str, soup: BeautifulSoup) -> Tag:
        if selector := cls.CONTENT_SELECTOR.get(domain, None):
            if content := soup.find(**selector):
                if domain == 'mp.weixin.qq.com':  # Special handling for WeChat articles
                    for img in content.find_all('img'):
                        if src := img.get('data-src'):
                            img['src'] = src
                return content
        return soup

    @classmethod
    def clean_html(cls, html: str, *, clean_svg: bool = False, clean_base64: bool = False,
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
            cleaned_html = cls.SPACE_PATTERN.sub(' ', cleaned_html).strip()

        return cleaned_html

    @classmethod
    def extract_images(cls, html: str) -> list[tuple[str, str]]:
        soup = BeautifulSoup(html, 'html.parser')
        all_imgs = []
        for img in soup.find_all("img"):
            if src := img.get("src", ""):
                all_imgs.append((src, img.get("alt", "")))
        return all_imgs

    @tracer.start_as_current_span("run")
    async def run(self, task: Task, trace_info: TraceInfo) -> dict:
        input_dict = task.input
        html = input_dict["html"]
        url = input_dict["url"]

        # Special case
        for processor in self.processors:
            if processor.hit(html, url):
                result = await processor.convert(html, url)
                return result.model_dump(exclude_none=True)

        domain: str = urlparse(url).netloc
        trace_info = trace_info.bind(domain=domain)

        result: GeneratedContent = await self.convert(domain, html, trace_info)
        result_dict: dict = result.model_dump(exclude_none=True)
        trace_info.info({k: v for k, v in result_dict.items() if k != "markdown"})
        return result_dict

    @tracer.start_as_current_span("get_images")
    async def get_images(self, html: str, markdown: str) -> list[Image]:
        extracted_images = self.extract_images(html)
        fetch_src_list: list[tuple[str, str]] = []

        for src, alt in extracted_images:
            if src in markdown:
                fetch_src_list.append((src, alt))

        return await HTMLReaderBaseProcessor.get_images(fetch_src_list)

    @tracer.start_as_current_span("get_title")
    async def get_title(self, markdown: str, raw_title: str, trace_info: TraceInfo) -> str:
        snippet: str = "\n".join(list(filter(bool, markdown.splitlines()))[:3])
        title: str = (
            await self.html_title_extractor.ainvoke({
                "title": raw_title, "snippet": snippet
            }, trace_info)
        ).title
        return title

    @classmethod
    def fix_lazy_images(cls, html: str) -> str:
        soup = BeautifulSoup(html, 'html.parser')

        # List of lazy loading attributes to check, in priority order
        lazy_attrs = ['data-src', 'data-lazy-src', 'data-original', 'data-lazy', 'data-url']

        # Common placeholder URL patterns
        placeholder_patterns = [
            '/t.png', '/placeholder', '/lazy', '/loading.gif',
            'data:image/', '1x1', 'blank.gif', 'grey.gif', 'transparent'
        ]

        for img in soup.find_all('img'):
            for attr in lazy_attrs:
                if lazy_src := img.get(attr):
                    # Skip if it's a base64 placeholder
                    if lazy_src.startswith('data:image/'):
                        continue

                    current_src = img.get('src', '')
                    # Check if current src is a placeholder
                    if not current_src or any(pattern in current_src.lower() for pattern in placeholder_patterns):
                        img['src'] = lazy_src
                        break

            # Handle responsive images (srcset)
            if data_srcset := img.get('data-srcset'):
                img['srcset'] = data_srcset

        return str(soup)

    @tracer.start_as_current_span("convert")
    async def convert(self, domain: str, raw_html: str, trace_info: TraceInfo) -> GeneratedContent:
        span = trace.get_current_span()
        html = self.fix_lazy_images(raw_html)
        html_doc = Document(html)

        selected_html: str = ''
        raw_title: str = html_doc.title()
        if domain in self.CONTENT_SELECTOR:
            with tracer.start_as_current_span("content_selector"):
                selected_html = self.content_selector(domain, BeautifulSoup(html, "html.parser")).prettify()
                cleaned_html = clean_attributes(tounicode(Document(selected_html)._html(True), method="html"))
                markdown = html2text(htmlmin.minify(cleaned_html, remove_empty_space=True), bodywidth=0).strip()
        else:
            html_summary: str = html_doc.summary().strip()
            markdown: str = html2text(htmlmin.minify(html_summary, remove_empty_space=True), bodywidth=0).strip()

            log_body: dict = {
                "len(html)": len(html),
                "len(html_summary)": len(html_summary),
                "compress_rate": f"{len(html_summary) * 100 / len(html): .2f}%",
                "len(markdown)": len(markdown),
            }
            trace_info.info(log_body)
            span.set_attributes(log_body)

        if not markdown:
            with tracer.start_as_current_span("llm_extract_content"):
                cleaned_html: str = clean_attributes(tounicode(Document(html)._html(True), method="html"))
                cleaned_html: str = self.clean_html(
                    cleaned_html, clean_svg=True, clean_base64=True,
                    remove_atts=True, compress=True, remove_empty_tag=True,
                )
                markdown = await self.html_content_extractor.ainvoke({"html": cleaned_html}, trace_info)

        images, title = await asyncio.gather(
            self.get_images(selected_html or html, markdown),
            self.get_title(markdown, raw_title, trace_info)
        )
        return GeneratedContent(title=title, markdown=markdown, images=images or None)
