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


class QuestionRecommender(BaseAgent[QuestionRecommendInput, QuestionRecommendOutput]):
    def __init__(self, config):
        super().__init__(
            config,
            QuestionRecommendInput,
            QuestionRecommendOutput,
            system_prompt_template="question_recommend.j2",
        )
