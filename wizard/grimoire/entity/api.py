from typing import Literal

from pydantic import BaseModel, Field

from wizard.grimoire.entity.retrieval import Citation
from wizard.grimoire.entity.tools import KnowledgeTool, WebSearchTool, Condition


class BaseChatRequest(BaseModel):
    session_id: str
    query: str


class InsertRequest(BaseModel):
    title: str = Field(description="Document title")
    content: str = Field(description="Document content")


class ChatRequest(BaseChatRequest, Condition):
    pass


class AgentRequest(BaseChatRequest):
    messages: list[dict] | None = Field(default_factory=list)
    tools: list[KnowledgeTool | WebSearchTool] | None = Field(default=None)
    citation_cnt: int = Field(default=0)
    enable_thinking: bool = Field(default=False)


class ChatBaseResponse(BaseModel):
    response_type: Literal["delta", "openai_message", "think_delta", "citation", "citation_list", "tool_call"]


class ChatOpenAIMessageResponse(ChatBaseResponse):
    response_type: Literal["openai_message"] = "openai_message"
    message: dict  # There would be trouble with openai.types.chat.ChatCompletionMessageParam


class ChatDeltaResponse(ChatBaseResponse):
    response_type: Literal["delta"] = "delta"
    delta: str


class ChatThinkDeltaResponse(ChatBaseResponse):
    response_type: Literal["think_delta"] = "think_delta"
    delta: str


class ChatCitationListResponse(ChatBaseResponse):
    response_type: Literal["citation_list"] = "citation_list"
    citation_list: list[Citation]


class FunctionCall(BaseModel):
    name: str
    arguments: dict


class ToolCall(BaseModel):
    id: str
    type: str
    function: FunctionCall


class ToolCallResponse(ChatBaseResponse):
    response_type: Literal["tool_call"] = "tool_call"
    tool_call: ToolCall
