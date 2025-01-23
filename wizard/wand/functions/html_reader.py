import asyncio
import json as jsonlib
import re

from openai import AsyncOpenAI

from common.trace_info import TraceInfo
from wizard.config import OpenAIConfig
from wizard.entity import Task
from wizard.wand.functions.base_function import BaseFunction


class HTMLReader(BaseFunction):
    SCRIPT_PATTERN: re.Pattern = re.compile(r"< *script.*?/ *script *>", re.IGNORECASE | re.MULTILINE | re.DOTALL)
    STYLE_PATTERN: re.Pattern = re.compile(r"< *style.*?/ *style *>", re.IGNORECASE | re.MULTILINE | re.DOTALL)
    META_PATTERN: re.Pattern = re.compile(r"< *meta.*?>", re.IGNORECASE | re.MULTILINE | re.DOTALL)
    COMMENT_PATTERN: re.Pattern = re.compile(r"< *!--.*?-- *>", re.IGNORECASE | re.MULTILINE | re.DOTALL)
    LINK_PATTERN: re.Pattern = re.compile(r"< *link.*?>", re.IGNORECASE | re.MULTILINE | re.DOTALL)
    BASE64_IMG_PATTERN: re.Pattern = re.compile(r'<img[^>]+src="data:image/[^;]+;base64,[^"]+"[^>]*>')
    SVG_PATTERN: re.Pattern = re.compile(r"(<svg[^>]*>)(.*?)(</svg>)", re.DOTALL)

    REMOVE_ATTRIBUTES_PATTERN_EXCEPT_IMG = re.compile(r"(<(?!img\b)[a-zA-Z][^>\s]*)(?:\s+[^>]*)?(>)", re.IGNORECASE)

    LINE_BREAK_PATTERN: re.Pattern = re.compile(r"\n+")
    SPACE_PATTERN: re.Pattern = re.compile(r"\s{2,}")

    MARKDOWN_EXTRACT_PATTERN: re.Pattern = re.compile(r"```markdown\n(.*?)\n```", re.DOTALL)
    JSON_EXTRACT_PATTERN: re.Pattern = re.compile(r"```json\n(.*?)\n```", re.DOTALL)

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

    def __init__(self, openai_config: OpenAIConfig):
        self.client = AsyncOpenAI(api_key=openai_config.api_key, base_url=openai_config.base_url)
        self.model = openai_config.model

    def replace_svg(self, html: str, new_content: str = "this is a placeholder") -> str:
        return self.SVG_PATTERN.sub(
            lambda match: f"{match.group(1)}{new_content}{match.group(3)}",
            html
        )

    def replace_base64_images(self, html: str, new_image_src: str = "#") -> str:
        return self.BASE64_IMG_PATTERN.sub(f'<img src="{new_image_src}"/>', html)

    def clean_html(self, html: str, clean_svg: bool = False, clean_base64: bool = False,
                   remove_attributes: bool = False, compress: bool = False) -> str:
        html = self.SCRIPT_PATTERN.sub("", html)
        html = self.STYLE_PATTERN.sub("", html)
        html = self.META_PATTERN.sub("", html)
        html = self.COMMENT_PATTERN.sub("", html)
        html = self.LINK_PATTERN.sub("", html)

        if clean_svg:
            html = self.replace_svg(html)
        if clean_base64:
            html = self.replace_base64_images(html)
        if remove_attributes:
            html = self.REMOVE_ATTRIBUTES_PATTERN_EXCEPT_IMG.sub(r"\1\2", html)
        if compress:
            html = self.LINE_BREAK_PATTERN.sub(" ", html)
            html = self.SPACE_PATTERN.sub(" ", html)
        return html

    @classmethod
    def create_prompt(cls, text: str, instruction: str = None, schema: str = None) -> str:
        """
        Create a prompt for the model with optional instruction and JSON schema.
        """
        if not instruction:
            instruction = "Extract the main content from the given HTML and convert it to Markdown format."
        if schema:
            instruction = "Extract the specified information from a list of news threads and present it in a structured JSON format."
            prompt = f"{instruction}\n```html\n{text}\n```\nThe JSON schema is as follows:```json\n{schema}\n```"
        else:
            prompt = f"{instruction}\n```html\n{text}\n```"

        return prompt

    async def extract_content(self, html: str, instruction: str = None, schema: str = None,
                              stream: bool = False) -> str | dict:
        prompt = self.create_prompt(html, instruction, schema)
        messages = [{"role": "user", "content": prompt}]
        openai_response = await self.client.chat.completions.create(
            model=self.model, messages=messages, temperature=0, stream=stream)
        if stream:
            response = ""
            async for chunk in openai_response:
                if delta := chunk.choices[0].delta.content:
                    response += delta
                    print(delta, flush=True, end="")
            print(flush=True)
        else:
            response = openai_response.choices[0].message.content
        if schema:
            str_json_response: str = self.JSON_EXTRACT_PATTERN.search(response).group(1)
            json_response: dict = jsonlib.loads(str_json_response)
            return json_response
        else:
            markdown_response: str = self.MARKDOWN_EXTRACT_PATTERN.search(response).group(1)
            return markdown_response

    async def run(self, task: Task, trace_info: TraceInfo, stream: bool = False) -> dict:
        input_dict = task.input
        html = input_dict["html"]
        url = input_dict["url"]

        cleaned_html = self.clean_html(html, clean_svg=True, clean_base64=True)
        trace_info.info({"len(html)": len(html), "len(cleaned_html)": len(cleaned_html)})

        metadata, content = await asyncio.gather(
            self.extract_content(cleaned_html, schema=self.SCHEMA),
            self.extract_content(cleaned_html, stream=stream)
        )

        filtered_metadata: dict = {k: v for k, v in metadata.items() if v != "Unknown"}

        title: str = filtered_metadata.get("title", input_dict.get("title", None)) or url
        content = "\n".join([row for row in content.split("\n") if row != f"# {title}"]).strip()

        result_dict: dict = {"url": url, "title": title, "markdown": content} | filtered_metadata
        trace_info.info({k: v for k, v in result_dict.items() if k != "markdown"})
        return result_dict
