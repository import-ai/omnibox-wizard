from jinja2 import Template
from pydantic import BaseModel, Field

from omnibox_wizard.worker.agent.base import BaseAgent


class HTMLContentExtractInput(BaseModel):
    html: str = Field(description="The title of the Webpage.")


class HTMLContentExtractor(BaseAgent[HTMLContentExtractInput, str]):
    def __init__(self, config):
        super().__init__(
            config,
            HTMLContentExtractInput,
            str,
            examples=None,
            system_prompt_template="html_content_extract.j2",
            user_prompt_template=Template("{{ html }}"),
        )
