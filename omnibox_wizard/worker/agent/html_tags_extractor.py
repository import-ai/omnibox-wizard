from jinja2 import Template
from pydantic import BaseModel, Field, field_validator

from omnibox_wizard.worker.agent.base import BaseAgent

RULES_CLOSING_TAG = "</user_classification_rules>"


class TagsExtractInput(BaseModel):
    title: str = Field(description="The title of the Webpage.")
    snippet: str = Field(
        description="The snippet of the Webpage, usually the first few lines of the content."
    )
    lang: str = Field(description="The expected output language.")
    tag_rules: str | None = Field(
        default=None,
        description="Optional user tagging rules from .omnibox/TAGS.md.",
    )

    @field_validator("tag_rules")
    @classmethod
    def strip_rules_delimiter(cls, value: str | None) -> str | None:
        """Keep TAGS.md content from closing the block it is rendered into.

        A teamspace TAGS.md is written by one member and applied to everyone
        else's resources, so its content is not necessarily trusted.
        """
        if not value:
            return value
        return value.replace(RULES_CLOSING_TAG, "")


class TagsExtractOutput(BaseModel):
    tags: list[str] = Field(description="A list of tags.")


examples = [
    (
        {
            "title": "(58 封私信) qwen3-0.6B这种小模型有什么实际意义和用途吗？ - 知乎",
            "snippet": "如果你接触过真正的线上服务，尤其是搜索推荐这类每天跑千万级请求的系统，你会发现，它这种小才是真正能干活的。\n很多业务链路对延迟的要求是严格到个位数毫秒的，QPS 又是成千上万，根本没办法把大模型塞进去。你要真上个 7B，别说延迟崩了，GPU 和预算都一起爆。这个时候，像 Qwen-0.6B 这种小模型就有优势了，资源吃得少，还能支持高并发。",
            "lang": "简体中文",
        },
        {"tags": ["技术", "人工智能", "机器学习"]},
    ),
    (
        {
            "title": "GPT-4.1 Prompting Guide",
            "snippet": "The GPT-4.1 family of models represents a significant step forward from GPT-4o in capabilities across coding, instruction following, and long context. In this prompting guide, we collate a series of important prompting tips derived from extensive internal testing to help developers fully leverage the improved abilities of this new model family.\nMany typical best practices still apply to GPT-4.1, such as providing context examples, making instructions as specific and clear as possible, and inducing planning via prompting to maximize model intelligence. However, we expect that getting the most out of this model will require some prompt migration. GPT-4.1 is trained to follow instructions more closely and more literally than its predecessors, which tended to more liberally infer intent from user and system prompts. This also means, however, that GPT-4.1 is highly steerable and responsive to well-specified prompts - if model behavior is different from what you expect, a single sentence firmly and unequivocally clarifying your desired behavior is almost always sufficient to steer the model on course.",
            "lang": "English",
        },
        {"tags": ["Technology", "Artificial Intelligence", "Machine Learning"]},
    ),
    (
        {
            "title": '全国夏粮小麦收获加速推进 "夏种夏管"有序进行_腾讯新闻',
            "snippet": "人民网记者 李栋\n夏粮产量占全年粮食总产量的1/4，其中小麦产量占夏粮产量的九成以上。当前，全国夏粮小麦收获加速推进，夏种夏管有序进行。\n中原熟，天下足。从5月19日开始大规模麦收，到6月9日基本结束，历时22天的河南全省麦收基本结束。数据显示，今年麦收期间，河南共投入联合收割机约21万台，累计收获小麦8464万亩，约占种植面积99.4%，机收率达99.8%。“三夏”机收任务圆满完成。",
            "lang": "English",
        },
        {"tags": ["Agriculture", "Economy", "Food Production"]},
    ),
]


class TagsExtractor(BaseAgent[TagsExtractInput, TagsExtractOutput]):
    def __init__(self, config):
        super().__init__(
            config,
            TagsExtractInput,
            TagsExtractOutput,
            examples=examples,
            system_prompt_template="tags_extract.j2",
            # The user's rules go in the user turn, after the few-shot
            # examples: those examples all answer with three plain, unprefixed
            # tags, and when the rules sat in the system prompt the examples
            # out-argued them and the rules were mostly ignored.
            user_prompt_template=Template(
                "<title>{{ title }}</title>\n"
                "<snippet>\n{{ snippet }}\n</snippet>\n"
                "<expected_output_lang>{{ lang }}</expected_output_lang>"
                "{% if tag_rules %}\n<user_classification_rules>\n{{ tag_rules }}\n</user_classification_rules>\n"
                "The rules above are defined by the user and override both the "
                "task guidelines and the example answers, including how many "
                "tags to return.{% endif %}"
            ),
        )
