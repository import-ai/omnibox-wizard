from datetime import datetime
from typing import Literal

from openai.types.chat import ChatCompletion

from omnibox_wizard.common import project_root
from omnibox_wizard.common.json_parser import parse_json
from omnibox_wizard.common.template_render import render_template
from omnibox_wizard.common.trace_info import TraceInfo
from omnibox_wizard.wizard.config import GrimoireOpenAIConfig


class CommonAI:

    def __init__(self, config: GrimoireOpenAIConfig):
        self.config: GrimoireOpenAIConfig = config
        with project_root.open("omnibox_wizard/resources/prompts/title.md") as f:
            self.title_system_prompt_template: str = f.read()
        with project_root.open("omnibox_wizard/resources/prompts/tag.md") as f:
            self.tag_system_prompt_template: str = f.read()

    async def _invoke(
            self, text: str, /,
            system_template: str, model_size: Literal["mini", "default", "large"],
            trace_info: TraceInfo | None = None
    ) -> dict:
        system_prompt: str = render_template(system_template, {
            "now": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "lang": "简体中文"
        })

        openai_response: ChatCompletion = await self.config[model_size].chat(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text}
            ],
            extra_body={"enable_thinking": False},
            extra_headers={"X-Trace-ID": trace_info.trace_id} if trace_info else None
        )
        str_response: str = openai_response.choices[0].message.content

        if trace_info:
            trace_info.info({
                "text": text,
                "str_response": str_response,
            })

        json_response: dict = parse_json(str_response)
        return json_response

    async def title(self, text: str, *, trace_info: TraceInfo | None = None) -> str:
        """
        Create title according to the given text
        """
        return (await self._invoke(text, self.title_system_prompt_template, "mini", trace_info))["title"]

    async def tags(self, text: str, *, trace_info: TraceInfo | None = None) -> list[str]:
        """
        Create tags according to the given text
        """
        return (await self._invoke(text, self.tag_system_prompt_template, "mini", trace_info))["tags"]
