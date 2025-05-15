from typing import List, Literal

from openai.types.chat import ChatCompletionMessageParam
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
    messages: List[ChatCompletionMessageParam] | None = Field(default=None)
    tools: List[KnowledgeTool | WebSearchTool] | None = Field(default=None)
    citation_cnt: int = Field(default=0)


class ChatBaseResponse(BaseModel):
    response_type: Literal["delta", "openai_message", "think_delta", "citation", "citation_list", "tool_call"]


class ChatOpenAIMessageResponse(ChatBaseResponse):
    response_type: Literal["openai_message"] = "openai_message"
    message: ChatCompletionMessageParam


class ChatDeltaResponse(ChatBaseResponse):
    response_type: Literal["delta"] = "delta"
    delta: str


class ChatThinkDeltaResponse(ChatBaseResponse):
    response_type: Literal["think_delta"] = "think_delta"
    delta: str


class ChatCitationListResponse(ChatBaseResponse):
    response_type: Literal["citation_list"] = "citation_list"
    citation_list: List[Citation]


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
