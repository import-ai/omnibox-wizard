from typing import Literal

from pydantic import BaseModel, Field

from wizard.grimoire.entity.retrieval import Citation
from wizard.grimoire.entity.tools import PrivateSearchTool, WebSearchTool


class BaseChatRequest(BaseModel):
    query: str


class ChatOptions(BaseModel):
    tools: list[PrivateSearchTool | WebSearchTool] | None = Field(default=None)
    enable_thinking: bool = Field(default=None)
    merge_search: bool = Field(default=None, description="Whether to merge search results from multiple tools.")


class MessageAttrs(ChatOptions):
    citations: list[Citation] = Field(default=None)


class MessageDto(BaseModel):
    message: dict
    attrs: MessageAttrs | None = Field(default=None)


class AgentRequest(BaseChatRequest, ChatOptions):
    conversation_id: str
    messages: list[MessageDto] | None = Field(default=None)


class ChatBaseResponse(BaseModel):
    response_type: Literal["bos", "delta", "eos", "error", "done"]


class ChatBOSResponse(ChatBaseResponse):
    response_type: Literal["bos"] = "bos"
    role: Literal["system", "user", "assistant", "tool"]


class ChatEOSResponse(ChatBaseResponse):
    response_type: Literal["eos"] = "eos"


class DeltaOpenAIMessage(BaseModel):
    content: str | None = Field(default=None)
    reasoning_content: str | None = Field(default=None)
    tool_calls: list[dict] | None = Field(default=None)
    tool_call_id: str | None = Field(default=None)


class ChatDeltaResponse(ChatBaseResponse):
    response_type: Literal["delta"] = "delta"
    message: DeltaOpenAIMessage
    attrs: MessageAttrs | None = Field(default=None, description="Attributes of the message.")


class ChatCitationsResponse(ChatBaseResponse):
    response_type: Literal["citations"] = "citations"
    citations: list[Citation]


class ChatErrorResponse(ChatBaseResponse):
    response_type: Literal["error"] = "error"
    message: str
