from typing import List, Literal, Tuple

from openai.types.chat import ChatCompletionMessageParam
from pydantic import BaseModel, Field

from wizard.grimoire.entity.retrieval import Citation

ToolType = Literal["knowledge", "web_search"]


class InsertRequest(BaseModel):
    title: str = Field(description="Document title")
    content: str = Field(description="Document content")


class Condition(BaseModel):
    namespace_id: str
    resource_ids: List[str] | None = Field(default=None)
    parent_ids: List[str] | None = Field(default=None)
    created_at: Tuple[float, float] | None = Field(default=None)
    updated_at: Tuple[float, float] | None = Field(default=None)


class Tool(BaseModel):
    type: ToolType


class KnowledgeTool(Tool):
    type: Literal["knowledge"] = "knowledge"
    namespace_id: str
    resource_ids: List[str] | None = Field(default=None)
    parent_ids: List[str] | None = Field(default=None)
    created_at: Tuple[float, float] | None = Field(default=None)
    updated_at: Tuple[float, float] | None = Field(default=None)


class WebSearchTool(Tool):
    type: Literal["web_search"] = "web_search"


class ChatRequest(Condition):
    session_id: str
    query: str


class AgentRequest(BaseModel):
    session_id: str
    query: str
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
    tool_calls: List[ToolCall]
