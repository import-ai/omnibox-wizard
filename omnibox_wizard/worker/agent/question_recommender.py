from pydantic import BaseModel, Field

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
    resource_ids: list[str] = Field(
        default_factory=list,
        description="IDs of recent_resources this question references.",
    )
    tag_ids: list[str] = Field(
        default_factory=list,
        description="IDs of recent_tags or resource tags this question references.",
    )
    conversation_ids: list[str] = Field(
        default_factory=list,
        description="IDs of recent_questions/conversations this question references.",
    )


class RecentTag(BaseModel):
    id: str | None = Field(default=None, description="ID of the tag.")
    name: str = Field(default="", description="Name of the tag.")


class RecentResource(BaseModel):
    id: str | None = Field(default=None, description="ID of the resource.")
    name: str = Field(default="", description="Name of the resource.")
    resource_type: str | None = Field(
        default=None, description="Type of the resource, e.g. doc, link, file."
    )
    metadata: dict = Field(
        default_factory=dict, description="Additional metadata of the resource."
    )
    tags: list[RecentTag] = Field(
        default_factory=list, description="Tags attached to the resource."
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
    conversation_id: str | None = Field(
        default=None, description="ID of the conversation that contains the question."
    )
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
    recent_tags: list[RecentTag] = Field(
        default_factory=list, description="Recently used tags."
    )
    recent_questions: list[RecentQuestion] = Field(
        default_factory=list, description="Questions the user asked recently."
    )


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
                    "id": "res_llm_intro",
                    "name": "LLM 入门指南",
                    "resource_type": "doc",
                    "tags": [{"id": "tag_tech", "name": "技术"}],
                    "content": "大语言模型（LLM）是一种基于海量文本训练的深度学习模型……",
                },
                {
                    "id": "res_rag_notes",
                    "name": "RAG 实践笔记",
                    "resource_type": "doc",
                    "tags": [
                        {"id": "tag_tech", "name": "技术"},
                        {"id": "tag_note", "name": "笔记"},
                    ],
                    "content": "RAG 通过检索外部知识增强生成质量，关键在于分块与召回……",
                },
                {
                    "id": "res_ai_kb",
                    "name": "AI 知识库搭建方案",
                    "resource_type": "link",
                    "metadata": {"url": "https://example.com/ai-kb"},
                    "tags": [],
                    "content": "本文介绍如何从零搭建团队 AI 知识库……",
                },
            ],
            "recent_tags": [
                {"id": "tag_tech", "name": "技术"},
                {"id": "tag_note", "name": "笔记"},
            ],
            "recent_questions": [
                {
                    "conversation_id": "conv_rag",
                    "question": "RAG 和微调有什么区别？",
                    "is_recommended": False,
                },
                {
                    "conversation_id": "conv_llm_summary",
                    "question": "帮我总结一下「LLM 入门指南」的核心内容",
                    "is_recommended": True,
                },
                {
                    "conversation_id": "conv_ai_kb_summary",
                    "question": "帮我总结一下「AI 知识库搭建方案」的要点",
                    "is_recommended": True,
                },
            ],
            "max_questions": 2,
        },
        {
            "questions": [
                {
                    "question": "帮我给「RAG 实践笔记」和「AI 知识库搭建方案」添加「AI 知识库」标签",
                    "intent": "tag_operation",
                    "reason": "用户近期更新了「RAG 实践笔记」和「AI 知识库搭建方案」，内容都与「AI 知识库」主题相关",
                    "resource_ids": ["res_rag_notes", "res_ai_kb"],
                    "tag_ids": [],
                    "conversation_ids": [],
                },
                {
                    "question": "结合「RAG 实践笔记」，RAG 落地时分块和召回策略应该怎么选？",
                    "intent": "qa",
                    "reason": "用户主动询问过 RAG 与微调的区别，且最近更新了「RAG 实践笔记」，适合追问；总结类推荐已被多次采纳，转而推荐问答类问题",
                    "resource_ids": ["res_rag_notes"],
                    "tag_ids": [],
                    "conversation_ids": ["conv_rag"],
                },
            ]
        },
    ),
    (
        {
            "recent_resources": [
                {
                    "id": "res_q3_roadmap",
                    "name": "Q3 Roadmap Draft",
                    "resource_type": "doc",
                    "tags": [{"id": "tag_planning", "name": "planning"}],
                    "content": "Q3 priorities: launch self-serve onboarding, improve retention...",
                },
                {
                    "id": "res_retro",
                    "name": "Team Retro Notes",
                    "resource_type": "doc",
                    "tags": [],
                    "content": "What went well: shipped billing revamp. What to improve: code review latency...",
                },
            ],
            "recent_tags": [{"id": "tag_planning", "name": "planning"}],
            "recent_questions": [],
            "max_questions": 1,
        },
        {
            "questions": [
                {
                    "question": "Summarize the key decisions in 「Team Retro Notes」",
                    "intent": "summarize",
                    "reason": "The user recently updated 「Team Retro Notes」",
                    "resource_ids": ["res_retro"],
                    "tag_ids": [],
                    "conversation_ids": [],
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
