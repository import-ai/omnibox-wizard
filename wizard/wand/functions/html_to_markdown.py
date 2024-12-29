import re

from markitdown._markitdown import HtmlConverter, DocumentConverterResult  # noqa

from wizard.wand.functions.base_function import BaseFunction


class HTMLToMarkdown(BaseFunction):
    def __init__(self):
        self.converter = HtmlConverter()
        self.pattern = re.compile(r"\n+")

    def _convert(self, html: str) -> dict:
        result = self.converter._convert(html)  # noqa
        return {"title": result.title, "markdown": result.text_content}

    async def run(self, input_dict: dict) -> dict:
        html = input_dict["html"]
        url = input_dict["url"]
        result_dict = self._convert(html)
        result_dict["markdown"] = self.pattern.sub("\n", result_dict["markdown"]).strip()
        return result_dict
