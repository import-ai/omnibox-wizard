from pydantic import BaseModel, Field, field_validator

from omnibox_wizard.worker.agent.base import BaseAgent


class RecommendedQuestion(BaseModel):
    question: str = Field(
        description="A question the user could ask the assistant, phrased in the user's voice."
    )
    intent: str = Field(
        description="Intent category of the question. One of: search, qa, summarize, tag_operation, organize, write."
    )
    reason: str = Field(
        description="Short explanation, grounded in the user's recent activity, of why this question is recommended."
    )


class RecentResource(BaseModel):
    name: str = Field(default="", description="Name of the resource.")
    resource_type: str | None = Field(
        default=None, description="Type of the resource, e.g. doc, link, file."
    )
    metadata: dict = Field(
        default_factory=dict, description="Additional metadata of the resource."
    )
    tags: list[str] = Field(
        default_factory=list, description="Tag names attached to the resource."
    )
    content: str | None = Field(
        default=None, description="Content of the resource, possibly truncated."
    )
    created_at: str | None = Field(
        default=None, description="When the resource was created, in ISO 8601 format."
    )
    updated_at: str | None = Field(
        default=None,
        description="When the resource was last updated, in ISO 8601 format.",
    )


class RecentQuestion(BaseModel):
    question: str = Field(description="The question the user asked.")
    is_recommended: bool = Field(
        default=False,
        description="Whether the conversation was started from a previously recommended question.",
    )


class QuestionRecommendContext(BaseModel):
    recent_resources: list[RecentResource] = Field(
        default_factory=list,
        description="The user's recently updated resources.",
    )
    recent_tags: list[str] = Field(
        default_factory=list, description="Names of recently used tags."
    )
    recent_questions: list[RecentQuestion] = Field(
        default_factory=list, description="Questions the user asked recently."
    )

    @field_validator("recent_questions", mode="before")
    @classmethod
    def _coerce_recent_questions(cls, v):
        if isinstance(v, list):
            return [{"question": item} if isinstance(item, str) else item for item in v]
        return v


class QuestionRecommendInput(QuestionRecommendContext):
    max_questions: int = Field(
        default=3, description="Maximum number of questions to generate."
    )


class QuestionRecommendOutput(BaseModel):
    questions: list[RecommendedQuestion] = Field(description="Recommended questions.")


examples = [
    (
        {
            "recent_resources": [
                {
                    "name": "LLM 入门指南",
                    "resource_type": "doc",
                    "tags": ["技术"],
                    "content": "大语言模型（LLM）是一种基于海量文本训练的深度学习模型……",
                },
                {
                    "name": "RAG 实践笔记",
                    "resource_type": "doc",
                    "tags": ["技术", "笔记"],
                    "content": "RAG 通过检索外部知识增强生成质量，关键在于分块与召回……",
                },
                {
                    "name": "AI 知识库搭建方案",
                    "resource_type": "link",
                    "metadata": {"url": "https://example.com/ai-kb"},
                    "tags": [],
                    "content": "本文介绍如何从零搭建团队 AI 知识库……",
                },
            ],
            "recent_tags": ["技术", "笔记"],
            "recent_questions": [
                {"question": "RAG 和微调有什么区别？", "is_recommended": False},
                {
                    "question": "帮我总结一下「LLM 入门指南」的核心内容",
                    "is_recommended": True,
                },
                {
                    "question": "帮我总结一下「AI 知识库搭建方案」的要点",
                    "is_recommended": True,
                },
            ],
            "max_questions": 2,
        },
        {
            "questions": [
                {
                    "question": "帮我给「RAG 实践笔记」和「AI 知识库搭建方案」添加 AI 知识库标签",
                    "intent": "tag_operation",
                    "reason": "用户近期更新了「RAG 实践笔记」和「AI 知识库搭建方案」，内容都与 AI 知识库相关",
                },
                {
                    "question": "RAG 落地时分块和召回策略应该怎么选？",
                    "intent": "qa",
                    "reason": "用户主动询问过 RAG 与微调的区别，且最近更新了「RAG 实践笔记」，适合追问；总结类推荐已被多次采纳，转而推荐问答类问题",
                },
            ]
        },
    ),
    (
        {
            "recent_resources": [
                {
                    "name": "Q3 Roadmap Draft",
                    "resource_type": "doc",
                    "tags": ["planning"],
                    "content": "Q3 priorities: launch self-serve onboarding, improve retention...",
                },
                {
                    "name": "Team Retro Notes",
                    "resource_type": "doc",
                    "tags": [],
                    "content": "What went well: shipped billing revamp. What to improve: code review latency...",
                },
            ],
            "recent_tags": ["planning"],
            "recent_questions": [],
            "max_questions": 1,
        },
        {
            "questions": [
                {
                    "question": "Summarize the key decisions in 「Team Retro Notes」",
                    "intent": "summarize",
                    "reason": "The user recently updated 「Team Retro Notes」",
                },
            ]
        },
    ),
]


class QuestionRecommender(BaseAgent[QuestionRecommendInput, QuestionRecommendOutput]):
    def __init__(self, config):
        super().__init__(
            config,
            QuestionRecommendInput,
            QuestionRecommendOutput,
            examples=examples,
            system_prompt_template="question_recommend.j2",
        )
