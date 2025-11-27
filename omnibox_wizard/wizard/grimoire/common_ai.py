from datetime import datetime
from typing import Literal

from openai.types.chat import ChatCompletion
from opentelemetry import propagate, trace

from common import project_root
from common.json_parser import parse_json
from common.template_render import render_template
from common.trace_info import TraceInfo
from omnibox_wizard.wizard.config import GrimoireOpenAIConfig

tracer = trace.get_tracer(__name__)


class CommonAI:
    def __init__(self, config: GrimoireOpenAIConfig):
        self.config: GrimoireOpenAIConfig = config
        with project_root.open("omnibox_wizard/resources/prompts/title.md") as f:
            self.title_system_prompt_template: str = f.read()
        with project_root.open("omnibox_wizard/resources/prompts/tag.md") as f:
            self.tag_system_prompt_template: str = f.read()

    @tracer.start_as_current_span("CommonAI._invoke")
    async def _invoke(
        self,
        text: str,
        /,
        system_template: str,
        model_size: Literal["mini", "default", "large"],
        lang: str | None = None,
        trace_info: TraceInfo | None = None,
    ) -> dict:
        system_prompt: str = render_template(
            system_template,
            {
                "now": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "lang": lang or "简体中文",
            },
        )

        headers = {}
        propagate.inject(headers)
        if trace_info:
            headers = headers | {"X-Request-Id": trace_info.request_id}

        openai_response: ChatCompletion = await self.config.get_config(model_size).chat(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text},
            ],
            extra_headers=headers if headers else None,
        )
        str_response: str = openai_response.choices[0].message.content

        if trace_info:
            trace_info.info(
                {
                    "text": text,
                    "str_response": str_response,
                }
            )

        json_response: dict = parse_json(str_response)
        return json_response

    @tracer.start_as_current_span("CommonAI.title")
    async def title(
        self, text: str, *, lang: str | None = None, trace_info: TraceInfo | None = None
    ) -> str:
        """
        Create title according to the given text
        """
        return (
            await self._invoke(
                text, self.title_system_prompt_template, "mini", lang, trace_info
            )
        )["title"]

    @tracer.start_as_current_span("CommonAI.tags")
    async def tags(
        self, text: str, *, lang: str | None = None, trace_info: TraceInfo | None = None
    ) -> list[str]:
        """
        Create tags according to the given text
        """
        return (
            await self._invoke(
                text, self.tag_system_prompt_template, "mini", lang, trace_info
            )
        )["tags"]
