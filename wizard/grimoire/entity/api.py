from typing import Literal

from pydantic import BaseModel, Field

from wizard.grimoire.entity.retrieval import Citation
from wizard.grimoire.entity.tools import KnowledgeTool, WebSearchTool, Condition


class BaseChatRequest(BaseModel):
    query: str


class InsertRequest(BaseModel):
    title: str = Field(description="Document title")
    content: str = Field(description="Document content")


class ChatRequest(BaseChatRequest, Condition):
    session_id: str


class AgentRequest(BaseChatRequest):
    conversation_id: str
    messages: list[dict] | None = Field(default_factory=list)
    tools: list[KnowledgeTool | WebSearchTool] | None = Field(default_factory=list)
    enable_thinking: bool = Field(default=False)
    current_cite_cnt: int = Field(default=0)


class ChatBaseResponse(BaseModel):
    response_type: Literal["delta", "openai_message", "think_delta", "citations", "tool_call"]


class OpenAIMessageAttrs(BaseModel):
    citations: list[Citation] = Field(default_factory=list)


class ChatOpenAIMessageResponse(ChatBaseResponse):
    response_type: Literal["openai_message"] = "openai_message"
    message: dict
    attrs: OpenAIMessageAttrs | None = Field(default=None, description="Attributes of the message.")


class ChatDeltaResponse(ChatBaseResponse):
    response_type: Literal["delta"] = "delta"
    delta: str


class ChatThinkDeltaResponse(ChatBaseResponse):
    response_type: Literal["think_delta"] = "think_delta"
    delta: str


class ChatCitationsResponse(ChatBaseResponse):
    response_type: Literal["citations"] = "citations"
    citations: list[Citation]


class FunctionCall(BaseModel):
    name: str
    arguments: dict


class ToolCall(BaseModel):
    id: str
    type: Literal["function"] = "function"
    function: FunctionCall


class ToolCallResponse(ChatBaseResponse):
    response_type: Literal["tool_call"] = "tool_call"
    tool_call: ToolCall
