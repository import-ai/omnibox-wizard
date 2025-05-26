from datetime import datetime

from openai.types.chat import ChatCompletion

from common import project_root
from common.json_parser import parse_json
from common.template_render import render_template
from common.trace_info import TraceInfo
from wizard.config import GrimoireOpenAIConfig


class CommonAI:

    def __init__(self, config: GrimoireOpenAIConfig):
        self.config: GrimoireOpenAIConfig = config
        with project_root.open("resources/prompts/title.md") as f:
            self.system_prompt_template: str = f.read()

    async def title(self, text: str, /, trace_info: TraceInfo | None = None) -> str:
        """
        Create title according to the given text
        """
        system_prompt: str = render_template(self.system_prompt_template, {
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

        if trace_info:
            trace_info.info({
                "text": text,
                "str_response": str_response,
            })

        json_response: dict = parse_json(str_response)
        return json_response["title"]
