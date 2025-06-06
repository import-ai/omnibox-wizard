from typing import Literal

from pydantic import BaseModel, Field

from wizard.grimoire.entity.retrieval import Citation
from wizard.grimoire.entity.tools import KnowledgeTool, WebSearchTool


class BaseChatRequest(BaseModel):
    query: str


class AgentRequest(BaseChatRequest):
    conversation_id: str
    messages: list[dict] | None = Field(default_factory=list)
    tools: list[KnowledgeTool | WebSearchTool] | None = Field(default_factory=list)
    enable_thinking: bool = Field(default=False)
    current_cite_cnt: int = Field(default=0)


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


class OpenAIMessageAttrs(BaseModel):
    citations: list[Citation] = Field(default_factory=list)


class ChatDeltaResponse(ChatBaseResponse):
    response_type: Literal["delta"] = "delta"
    message: DeltaOpenAIMessage
    attrs: OpenAIMessageAttrs | None = Field(default=None, description="Attributes of the message.")


class ChatCitationsResponse(ChatBaseResponse):
    response_type: Literal["citations"] = "citations"
    citations: list[Citation]


class ChatErrorResponse(ChatBaseResponse):
    response_type: Literal["error"] = "error"
    message: str
