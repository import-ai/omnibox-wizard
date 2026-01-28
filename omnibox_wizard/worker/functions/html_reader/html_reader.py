import asyncio
import json as jsonlib
import re
from functools import partial
from urllib.parse import urlparse, urljoin

import htmlmin
from bs4 import BeautifulSoup, Comment
from html2text import html2text
from lxml.etree import tounicode
from opentelemetry import trace
from readability import Document
from readability.cleaners import clean_attributes

from common.trace_info import TraceInfo
from omnibox_wizard.worker.agent.html_content_extractor import HTMLContentExtractor
from omnibox_wizard.worker.agent.html_title_extractor import (
    HTMLTitleExtractor,
    HTMLTitleExtractOutput,
)
from omnibox_wizard.worker.config import WorkerConfig
from wizard_common.worker.entity import Task, Image, GeneratedContent, TaskFunction
from omnibox_wizard.worker.functions.base_function import BaseFunction
from omnibox_wizard.worker.functions.html_reader.processors.base import (
    HTMLReaderBaseProcessor,
)
from omnibox_wizard.worker.functions.html_reader.processors.green_note import (
    GreenNoteProcessor,
)
from omnibox_wizard.worker.functions.html_reader.processors.green_notice import (
    GreenNoticeProcessor,
)
from omnibox_wizard.worker.functions.html_reader.processors.okjike_m import (
    OKJikeMProcessor,
)
from omnibox_wizard.worker.functions.html_reader.processors.okjike_web import (
    OKJikeWebProcessor,
)
from omnibox_wizard.worker.functions.html_reader.processors.red_note import (
    RedNoteProcessor,
)
from omnibox_wizard.worker.functions.html_reader.processors.x import XProcessor
from omnibox_wizard.worker.functions.html_reader.selectors.base import BaseSelector
from omnibox_wizard.worker.functions.html_reader.selectors.common import CommonSelector
from omnibox_wizard.worker.functions.html_reader.selectors.zhihu_a import (
    ZhihuAnswerSelector,
)
from omnibox_wizard.worker.functions.html_reader.selectors.zhihu_q import (
    ZhihuQuestionSelector,
)
from omnibox_wizard.worker.functions.html_reader.selectors.lambda_selector import (
    LambdaSelector,
)

json_dumps = partial(jsonlib.dumps, separators=(",", ":"), ensure_ascii=False)
tracer = trace.get_tracer("HTMLReaderV2")


class Preprocessor:
    SPACE_PATTERN: re.Pattern = re.compile(r"\s{2,}")

    @classmethod
    def clean_html(
        cls,
        html: str,
        *,
        clean_svg: bool = False,
        clean_base64: bool = False,
        compress: bool = False,
        remove_empty_tag: bool = False,
        remove_atts: bool = False,
        allowed_attrs: set | None = None,
    ) -> str:
        soup = BeautifulSoup(html, "html.parser")

        # Remove script, style, meta, and link tags
        for tag_name in ["script", "style", "meta", "link"]:
            for tag in soup.find_all(tag_name):
                tag.decompose()

        # Remove comments
        for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
            comment.extract()

        # Clean SVG tags if clean_svg is True
        if clean_svg:
            for svg_tag in soup.find_all("svg"):
                # Replace the contents of the svg tag with a placeholder
                svg_tag.clear()

        # Clean base64 images if clean_base64 is True
        if clean_base64:
            for img_tag in soup.find_all("img"):
                src = img_tag.get("src", "")
                if src.startswith("data:image/") and "base64," in src:
                    img_tag["src"] = "#"

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
                if (tag.name and tag.name.lower() == "img") or tag.find(
                    "img"
                ) is not None:
                    continue
                if not tag.get_text(strip=True):
                    tag.decompose()

        # Convert the modified soup back to a string
        cleaned_html = str(soup)

        # Compress whitespace if compress is True
        if compress:
            # Replace multiple whitespace characters with a single space
            cleaned_html = cls.SPACE_PATTERN.sub(" ", cleaned_html).strip()

        return cleaned_html

    @classmethod
    def extract_images(cls, html: str) -> list[tuple[str, str]]:
        soup = BeautifulSoup(html, "html.parser")
        all_imgs = []
        for img in soup.find_all("img"):
            if src := img.get("src", ""):
                all_imgs.append((src, img.get("alt", "")))
        return all_imgs

    @classmethod
    def convert_img_src(cls, url: str, html: str) -> str:
        soup = BeautifulSoup(html, "html.parser")
        for img in soup.find_all("img"):
            if src := img.get("src", ""):
                img["src"] = urljoin(url, str(src))
        return str(soup)

    @classmethod
    def remove_noscript(cls, html: str) -> str:
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup.find_all("noscript"):
            tag.decompose()
        return str(soup)

    @classmethod
    def fix_lazy_images(cls, html: str) -> str:
        soup = BeautifulSoup(html, "html.parser")

        # List of lazy loading attributes to check, in priority order
        lazy_attrs = [
            "data-src",
            "data-lazy-src",
            "data-original",
            "data-lazy",
            "data-url",
        ]

        # Common placeholder URL patterns
        placeholder_patterns = [
            "/t.png",
            "/placeholder",
            "/lazy",
            "/loading.gif",
            "data:image/",
            "1x1",
            "blank.gif",
            "grey.gif",
            "transparent",
        ]

        for img in soup.find_all("img"):
            for attr in lazy_attrs:
                if lazy_src := img.get(attr):
                    # Skip if it's a base64 placeholder
                    if lazy_src.startswith("data:image/"):
                        continue

                    current_src = img.get("src", "")
                    # Check if current src is a placeholder
                    if not current_src or any(
                        pattern in current_src.lower()
                        for pattern in placeholder_patterns
                    ):
                        img["src"] = lazy_src
                        break

            # Handle responsive images (srcset)
            if data_srcset := img.get("data-srcset"):
                img["srcset"] = data_srcset

        return str(soup)


class HTMLReaderV2(BaseFunction):
    CONTENT_SELECTOR = {
        "github.com": {"name": "article", "class_": "markdown-body"},
        "medium.com": {"name": "article"},
        "mp.weixin.qq.com": {"name": "div", "class_": "rich_media_content"},
        "news.qq.com": {"name": "div", "class_": "content-article"},
        "zhuanlan.zhihu.com": {"name": "article"},
        "www.zhihu.com": {"class_": "RichText", "select_all": True},
        "www.163.com": {"name": "div", "class_": "post_body"},
        "x.com": {"name": "div", "attrs": {"data-testid": "tweetText"}},
        "www.reddit.com": {"name": "shreddit-post-text-body"},
    }

    def __init__(self, config: WorkerConfig):
        self.html_title_extractor = HTMLTitleExtractor(
            config.grimoire.openai.get_config("mini")
        )
        self.html_content_extractor = HTMLContentExtractor(
            config.grimoire.openai.get_config("mini")
        )
        self.processors: list[HTMLReaderBaseProcessor] = [
            GreenNoteProcessor(config=config),
            GreenNoticeProcessor(config=config),
            RedNoteProcessor(config=config),
            OKJikeWebProcessor(config=config),
            OKJikeMProcessor(config=config),
            XProcessor(config=config),
        ]
        self.selectors: list[BaseSelector] = [
            CommonSelector(
                "github.com", {"name": "article", "class_": "markdown-body"}
            ),
            CommonSelector("medium.com", {"name": "article"}),
            CommonSelector(
                "mp.weixin.qq.com", {"name": "div", "class_": "rich_media_content"}
            ),
            CommonSelector("news.qq.com", {"name": "div", "class_": "content-article"}),
            ZhihuAnswerSelector(),
            ZhihuQuestionSelector(),
            CommonSelector("www.zhihu.com", {"class_": "RichText"}, True),
            CommonSelector("zhuanlan.zhihu.com", {"name": "article"}),
            CommonSelector("www.163.com", {"name": "div", "class_": "post_body"}),
            CommonSelector(
                "x.com", {"name": "div", "attrs": {"data-testid": "tweetText"}}
            ),
            CommonSelector("www.reddit.com", {"name": "shreddit-post-text-body"}),
            LambdaSelector(
                lambda parsed, soup: parsed.netloc == "www.dedao.cn"
                and "/share/" in parsed.path,
                {"id": "article-box"},
            ),
        ]

    def get_processor(self, html: str, url: str) -> HTMLReaderBaseProcessor | None:
        for processor in self.processors:
            if processor.hit(html, url):
                return processor
        return None

    def get_selector(self, url: str, soup: BeautifulSoup) -> BaseSelector | None:
        for selector in self.selectors:
            if selector.hit(url, soup):
                return selector
        return None

    @tracer.start_as_current_span("run")
    async def run(self, task: Task, trace_info: TraceInfo) -> dict:
        result_dict: dict = await self.main(task, trace_info)
        if result_dict.get("markdown"):
            extract_tags_task = task.create_next_task(
                TaskFunction.EXTRACT_TAGS, {"text": result_dict["markdown"]}
            )
            result_dict.setdefault("next_tasks", []).append(
                extract_tags_task.model_dump()
            )
        return result_dict

    @tracer.start_as_current_span("main")
    async def main(self, task: Task, trace_info: TraceInfo) -> dict:
        input_dict = task.input
        html = input_dict["html"]
        url = input_dict["url"]

        html = Preprocessor.fix_lazy_images(html)
        html = Preprocessor.convert_img_src(url, html)
        html = Preprocessor.remove_noscript(html)

        # Special case
        if processor := self.get_processor(html, url):
            with tracer.start_as_current_span("html_processor"):
                result = await processor.convert(html, url)
                return result.model_dump(exclude_none=True)

        domain: str = urlparse(url).netloc
        trace_info = trace_info.bind(domain=domain)

        result: GeneratedContent = await self.convert(
            url=url, html=html, trace_info=trace_info, task=task
        )
        result_dict: dict = result.model_dump(exclude_none=True)
        return result_dict

    @tracer.start_as_current_span("get_images")
    async def get_images(self, html: str, markdown: str) -> list[Image]:
        extracted_images = Preprocessor.extract_images(html)
        fetch_src_list: list[tuple[str, str]] = []

        for src, alt in extracted_images:
            if src in markdown:
                fetch_src_list.append((src, alt))

        return await HTMLReaderBaseProcessor.get_images(fetch_src_list)

    @tracer.start_as_current_span("get_title")
    async def get_title(
        self, markdown: str, raw_title: str, trace_info: TraceInfo
    ) -> str:
        span = trace.get_current_span()
        try:
            snippet: str = markdown.strip()[:512]
            title_extract_output: HTMLTitleExtractOutput = (
                await self.html_title_extractor.ainvoke(
                    {"title": raw_title, "snippet": snippet}, trace_info
                )
            )
            return title_extract_output.title
        except Exception as e:
            span.record_exception(e)
            return raw_title

    @tracer.start_as_current_span("content_selector")
    def parse_with_selector(
        self, selector: BaseSelector, url: str, html: str, soup: BeautifulSoup
    ) -> str:
        span = trace.get_current_span()
        selected_html: str = selector.select(url, soup).prettify()
        cleaned_html: str = clean_attributes(
            tounicode(Document(selected_html)._html(True), method="html")
        )
        markdown: str = html2text(
            htmlmin.minify(cleaned_html, remove_empty_space=True), bodywidth=0
        ).strip()

        span.set_attributes(
            {
                "len(html)": len(html),
                "len(html_summary)": len(selected_html),
                "len(cleaned_html)": len(cleaned_html),
                "len(markdown)": len(markdown),
            }
        )
        return markdown

    @tracer.start_as_current_span("reader_summary")
    def parse_with_reader(self, html_doc: Document, html: str) -> str:
        span = trace.get_current_span()
        html_summary: str = html_doc.summary().strip()
        markdown: str = html2text(
            htmlmin.minify(html_summary, remove_empty_space=True), bodywidth=0
        ).strip()

        span.set_attributes(
            {
                "len(html)": len(html),
                "len(html_summary)": len(html_summary),
                "compress_rate": f"{len(html_summary) * 100 / len(html): .2f}%",
                "len(markdown)": len(markdown),
            }
        )
        return markdown

    @tracer.start_as_current_span("llm_extract_content")
    async def parse_with_llm(self, html: str, trace_info: TraceInfo) -> str:
        span = trace.get_current_span()
        tools_cleaned_html: str = clean_attributes(
            tounicode(Document(html)._html(True), method="html")
        )
        cleaned_html: str = Preprocessor.clean_html(
            tools_cleaned_html,
            clean_svg=True,
            clean_base64=True,
            remove_atts=True,
            compress=True,
            remove_empty_tag=True,
        )
        span.set_attributes(
            {
                "len(html)": len(html),
                "len(tools_cleaned_html)": len(tools_cleaned_html),
                "len(cleaned_html)": len(cleaned_html),
            }
        )

        if len(cleaned_html) < 128 * 1024:
            markdown = await self.html_content_extractor.ainvoke(
                {"html": cleaned_html}, trace_info
            )
            span.set_attributes({"len(markdown)": len(markdown)})
            return markdown
        return ""

    @tracer.start_as_current_span("convert")
    async def convert(
        self, url: str, html: str, trace_info: TraceInfo, task: Task | None = None
    ) -> GeneratedContent:
        html_doc = Document(html)

        selected_html: str = ""
        raw_title: str = html_doc.title()

        markdown: str = ""

        span = trace.get_current_span()
        soup = BeautifulSoup(html, "html.parser")
        try:
            if selector := self.get_selector(url, soup):
                markdown = self.parse_with_selector(selector, url, html, soup)
            else:
                markdown = self.parse_with_reader(html_doc, html)
        except Exception as e:
            span.record_exception(e)

        if not markdown:
            try:
                markdown = await self.parse_with_llm(html, trace_info)
            except Exception as e:
                span.record_exception(e)

        if not markdown:
            try:
                with tracer.start_as_current_span("fallback_html2text") as span:
                    markdown = html2text(html)
                    span.set_attributes({"len(markdown)": len(markdown)})
            except Exception as e:
                span.record_exception(e)

        images, title = await asyncio.gather(
            self.get_images(html=selected_html or html, markdown=markdown),
            self.get_title(markdown, raw_title, trace_info),
        )
        return GeneratedContent(title=title, markdown=markdown, images=images or None)
