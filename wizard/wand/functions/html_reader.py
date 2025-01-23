import asyncio
import json as jsonlib
import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup, Comment, Tag
from openai import AsyncOpenAI

from common.trace_info import TraceInfo
from wizard.config import OpenAIConfig, ReaderConfig
from wizard.entity import Task
from wizard.wand.functions.base_function import BaseFunction


class HTMLReader(BaseFunction):
    LINE_BREAK_PATTERN: re.Pattern = re.compile(r"\n+")
    SPACE_PATTERN: re.Pattern = re.compile(r"\s{2,}")

    SCHEMA = jsonlib.dumps({
        "type": "object",
        "properties": {
            "title": {
                "type": "string"
            },
            "author": {
                "type": "string"
            },
            "date": {
                "type": "string"
            }
        },
        "required": ["title", "author", "date"]
    }, ensure_ascii=False, indent=2)

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
        }
    }

    def __init__(self, reader_config: ReaderConfig):
        openai_config: OpenAIConfig = reader_config.openai
        self.client = AsyncOpenAI(api_key=openai_config.api_key, base_url=openai_config.base_url)
        self.model: str = openai_config.model
        self.timeout: float = reader_config.timeout

    @classmethod
    def content_selector(cls, url: str, soup: BeautifulSoup) -> Tag:
        domain = url.split("/")[2]
        if selector := cls.CONTENT_SELECTOR.get(domain, None):
            if content := soup.find(**selector):
                return content
        return soup

    def clean_html(self, url: str, html: str, *, clean_svg: bool = False, clean_base64: bool = False,
                   compress: bool = False, remove_empty_tag: bool = False, remove_atts: bool = False,
                   allowed_attrs: set | None = None, enable_content_selector: bool = False) -> str:
        soup = BeautifulSoup(html, 'html.parser')

        if enable_content_selector:
            soup = self.content_selector(url, soup)

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

    @classmethod
    def create_prompt(cls, text: str, instruction: str = None, schema: str = None) -> str:
        """
        Create a prompt for the model with optional instruction and JSON schema.
        """
        if not instruction:
            instruction = "Extract the main content from the given HTML and convert it to Markdown format."
        if schema:
            instruction = ("Extract the specified information from the given HTML and present it in a structured JSON "
                           "format. If any of the fields are not found in the HTML document, set their values to "
                           "`Unknown` in the JSON output.")
            prompt = f"{instruction}\n```html\n{text}\n```\nThe JSON schema is as follows:```json\n{schema}\n```"
        else:
            prompt = f"{instruction}\n```html\n{text}\n```"

        return prompt

    @classmethod
    async def get_response(cls, openai_response, stream: bool) -> str:
        if stream:
            response = ""
            async for chunk in openai_response:
                if delta := chunk.choices[0].delta.content:
                    response += delta
                    print(delta, flush=True, end="")
            print(flush=True)
        else:
            response = openai_response.choices[0].message.content
        return response

    @classmethod
    def get_code_block(cls, markdown: str, lang: str) -> str:
        head_sep: str = f"```{lang}\n"
        tail_sep: str = "\n```"

        partial_content: str = head_sep.join(markdown.split(head_sep)[1:]).strip()
        content: str = tail_sep.join(partial_content.split(tail_sep)[:-1]).strip()
        return content

    async def extract_content(self, html: str, instruction: str = None, schema: str = None,
                              stream: bool = False) -> str | dict:
        prompt = self.create_prompt(html, instruction, schema)
        messages = [{"role": "user", "content": prompt}]
        openai_response = await self.client.chat.completions.create(
            model=self.model, messages=messages, temperature=0, stream=stream)
        response = await self.get_response(openai_response, stream)
        if schema:
            str_json_response: str = self.get_code_block(response, "json")
            json_response: dict = jsonlib.loads(str_json_response)
            return json_response
        else:
            markdown_response: str = self.get_code_block(response, "markdown")
            return markdown_response

    async def run(self, task: Task, trace_info: TraceInfo, stream: bool = False) -> dict:
        input_dict = task.input
        html = input_dict["html"]
        url = input_dict["url"]

        domain: str = urlparse(url).netloc
        trace_info = trace_info.bind(domain=domain)

        cleaned_html = self.clean_html(url, html, clean_svg=True, clean_base64=True, remove_atts=True,
                                       compress=True, remove_empty_tag=True, enable_content_selector=True)
        trace_info.info({
            "len(html)": len(html),
            "len(cleaned_html)": len(cleaned_html),
            "compress_rate": f"{len(cleaned_html) * 100 / len(html): .2f}%"
        })

        metadata_task = asyncio.create_task(self.extract_content(cleaned_html, schema=self.SCHEMA))
        content_task = asyncio.create_task(self.extract_content(cleaned_html, stream=stream))

        try:
            metadata = await asyncio.wait_for(metadata_task, timeout=self.timeout)
        except asyncio.TimeoutError:
            trace_info.error({"error": "metadata TimeoutError"})
            metadata = {}

        try:
            content = await asyncio.wait_for(content_task, timeout=self.timeout)
        except asyncio.TimeoutError:
            trace_info.error({"error": "content TimeoutError"})
            content = "Timeout, please retry."

        filtered_metadata: dict = {k: v for k, v in metadata.items() if v != "Unknown"}

        title: str = filtered_metadata.get("title", input_dict.get("title", None)) or url
        content = "\n".join([row for row in content.split("\n") if row != f"# {title}"]).strip()

        result_dict: dict = {"url": url, "title": title, "markdown": content} | filtered_metadata
        trace_info.info({k: v for k, v in result_dict.items() if k != "markdown"})
        return result_dict
