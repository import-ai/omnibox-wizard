from jinja2 import Template
from pydantic import BaseModel, Field

from omnibox_wizard.worker.agent.base import BaseAgent


class ChatTitleGenerateInput(BaseModel):
    text: str = Field(description="User's text.")
    lang: str = Field(description="User's preference language.")


class ChatTitleGenerateOutput(BaseModel):
    title: str = Field(description="Generated title from user's text.")


examples = [
    (
        {
            "text": "我创建了一个用于存放我的钢琴谱和吉他谱的网站，请给这个网站起一个名字。",
            "lang": "English",
        },
        {"title": "Website Name Suggestions"},
    ),
    (
        {
            "text": "猫叼塑料袋走来走去一般是为什么？",
            "lang": "简体中文",
        },
        {"title": "猫叼塑料袋的原因"},
    ),
    (
        {
            "text": "I have a python project, its runtime need 2GB disk space, is there anyway to reduce the dist usage?",
            "lang": "English",
        },
        {"title": "Reducing disk usage in Python projects"},
    ),
]


class ChatTitleGenerator(BaseAgent[ChatTitleGenerateInput, ChatTitleGenerateOutput]):
    def __init__(self, config):
        super().__init__(
            config,
            ChatTitleGenerateInput,
            ChatTitleGenerateOutput,
            examples=examples,
            system_prompt_template="chat_title.j2",
            user_prompt_template=Template(
                "<title>{{ text }}</title>\n<expected_output_lang>{{ lang }}</expected_output_lang>"
            ),
        )
