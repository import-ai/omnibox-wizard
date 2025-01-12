import asyncio
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from markitdown._markitdown import HtmlConverter, DocumentConverterResult  # noqa
from openai import AsyncOpenAI

from common import project_root
from wizard.config import Config, OpenAIConfig
from wizard.entity import Task
from wizard.wand.functions.base_function import BaseFunction


class HTMLToMarkdown(BaseFunction):
    def __init__(self, config: Config):
        self.converter = HtmlConverter()
        self.pattern = re.compile(r"\n+")

        openai_config: OpenAIConfig = config.grimoire.openai
        self.client = AsyncOpenAI(api_key=openai_config.api_key, base_url=openai_config.base_url)
        self.model = openai_config.model

        with project_root.open("resources/prompts/functions/content_extract.md") as f:
            self.template: str = f.read()
        self.executor = ThreadPoolExecutor()

    def _convert(self, html: str) -> dict:
        result = self.converter._convert(html)  # noqa
        return {"title": result.title, "markdown": result.text_content}

    async def _extract(self, url: str, title: str, markdown: str) -> str:
        system = self.template.format_map({"now": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": "\n\n".join([
                f"网页 URL：{url}",
                f"网页标题：{title}",
                f"以下是网页内容：\n{markdown}"
            ])}
        ]
        openai_response = await self.client.chat.completions.create(model=self.model, messages=messages, temperature=0)
        response = openai_response.choices[0].message.content
        return response

    async def run(self, task: Task) -> dict:
        input_dict = task.input
        html = input_dict["html"]
        url = input_dict["url"]
        title = input_dict.get("title", "")

        loop = asyncio.get_event_loop()
        convert_result: dict = await loop.run_in_executor(self.executor, self._convert, html)

        markdown = convert_result["markdown"]
        markdown = self.pattern.sub("\n", markdown).strip()
        title = title or convert_result["title"]
        extracted_content: str = await self._extract(url, title, markdown)

        result_dict: dict = {
            "url": url,
            "title": title,
            "markdown": {
                "raw": markdown,
                "extracted": extracted_content
            }
        }
        return result_dict
