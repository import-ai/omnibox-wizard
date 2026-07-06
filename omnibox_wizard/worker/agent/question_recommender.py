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


class QuestionRecommendInput(BaseModel):
    recent_resources: list[str] = Field(
        default_factory=list,
        description="Names of the user's recently updated resources.",
    )
    recent_tags: list[str] = Field(
        default_factory=list, description="Names of recently used tags."
    )
    recent_questions: list[str] = Field(
        default_factory=list, description="Questions the user asked recently."
    )
    max_questions: int = Field(
        default=3, description="Maximum number of questions to generate."
    )


class QuestionRecommendOutput(BaseModel):
    questions: list[RecommendedQuestion] = Field(description="Recommended questions.")


examples = [
    (
        {
            "recent_resources": ["LLM 入门指南", "RAG 实践笔记", "AI 知识库搭建方案"],
            "recent_tags": ["技术", "笔记"],
            "recent_questions": ["RAG 和微调有什么区别？"],
            "max_questions": 2,
        },
        {
            "questions": [
                {
                    "question": "帮我把 AI 知识库相关资源都打上 AI 知识库标签",
                    "intent": "tag_operation",
                    "reason": "用户近期有多个 AI 知识库相关资源",
                },
                {
                    "question": "帮我总结一下 RAG 实践笔记的要点",
                    "intent": "summarize",
                    "reason": "用户最近更新了 RAG 实践笔记，并询问过 RAG 相关问题",
                },
            ]
        },
    ),
    (
        {
            "recent_resources": ["Q3 Roadmap Draft", "Team Retro Notes"],
            "recent_tags": ["planning"],
            "recent_questions": [],
            "max_questions": 1,
        },
        {
            "questions": [
                {
                    "question": "Summarize the key decisions in my Team Retro Notes",
                    "intent": "summarize",
                    "reason": "The user recently updated Team Retro Notes",
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
