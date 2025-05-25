import json as jsonlib
import re
from datetime import datetime

from openai.types.chat import ChatCompletion

from common import project_root
from common.trace_info import TraceInfo
from wizard.config import GrimoireOpenAIConfig


class JSONParser:
    _json_markdown_re = re.compile(r"```json(.*)", re.DOTALL)
    _json_strip_chars = " \n\r\t`"

    def __call__(self, text: str) -> dict | list:
        if (match := self._json_markdown_re.search(text)) is not None:
            json_string: str = match.group(1)
            json_string: str = json_string.strip(self._json_strip_chars)
            return jsonlib.loads(json_string)
        return jsonlib.loads(text)


class CommonAI:

    def __init__(self, config: GrimoireOpenAIConfig):
        self.config: GrimoireOpenAIConfig = config
        self.json_parser = JSONParser()
        with project_root.open("resources/prompts/title.md") as f:
            self.system_prompt_template: str = f.read()

    async def title(self, text: str, /, trace_info: TraceInfo | None = None) -> str:
        """
        Create title according to the given text
        """
        system_prompt: str = self.system_prompt_template.format_map({
            "now": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "lang": "简体中文"
        })

        openai_response: ChatCompletion = await self.config["mini"].chat(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text}
            ],
            extra_body={"enable_thinking": False}
        )
        str_response: str = openai_response.choices[0].message.content
        json_response: dict = self.json_parser(str_response)
        if trace_info:
            trace_info.info({
                "text": text,
                "response": str_response,
            })
        return json_response["title"]
