from typing import Literal

from pydantic import BaseModel, Field

from omnibox_wizard.wizard.grimoire.entity.retrieval import Citation
from omnibox_wizard.wizard.grimoire.entity.tools import (
    PrivateSearchTool,
    WebSearchTool,
    ProductDocsTool,
    GetResourcesTool,
    GetChildrenTool,
    GetParentTool,
    FilterByTimeTool,
    FilterByTagTool,
    FilterByKeywordTool,
)


class BaseChatRequest(BaseModel):
    query: str


class ChatRequestOptions(BaseModel):
    tools: list[
        PrivateSearchTool
        | WebSearchTool
        | ProductDocsTool
        | GetResourcesTool
        | GetChildrenTool
        | GetParentTool
        | FilterByTimeTool
        | FilterByTagTool
        | FilterByKeywordTool
    ] | None = Field(default=None)
    enable_thinking: bool | None = Field(default=None)
    merge_search: bool | None = Field(
        default=None, description="Whether to merge search results from multiple tools."
    )
    force_search: bool | None = Field(
        default=None, description="Whether to force search."
    )
    lang: Literal["简体中文", "English"] | None = Field(
        default=None, description="Language of the response."
    )


class MessageAttrs(ChatRequestOptions):
    citations: list[Citation] = Field(default=None)


class MessageDto(BaseModel):
    message: dict
    attrs: MessageAttrs | None = Field(default=None)


class AgentRequest(BaseChatRequest, ChatRequestOptions):
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
    attrs: MessageAttrs | None = Field(
        default=None, description="Attributes of the message."
    )


class ChatCitationsResponse(ChatBaseResponse):
    response_type: Literal["citations"] = "citations"
    citations: list[Citation]


class ChatErrorResponse(ChatBaseResponse):
    response_type: Literal["error"] = "error"
    message: str
