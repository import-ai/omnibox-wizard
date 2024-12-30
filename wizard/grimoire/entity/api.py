from typing import List, Literal, Tuple

from pydantic import BaseModel, Field

from wizard.grimoire.entity.retrieval import Citation


class InsertRequest(BaseModel):
    title: str = Field(description="Document title")
    content: str = Field(description="Document content")


class Condition(BaseModel):
    namespace_id: str
    resource_ids: List[str] | None = Field(default=None)
    parent_ids: List[str] | None = Field(default=None)
    created_at: Tuple[float, float] | None = Field(default=None)
    updated_at: Tuple[float, float] | None = Field(default=None)


class ChatRequest(Condition):
    session_id: str
    query: str


class ChatBaseResponse(BaseModel):
    response_type: Literal["delta", "citation", "citation_list"]


class ChatDeltaResponse(ChatBaseResponse):
    response_type: Literal["delta"] = "delta"
    delta: str


class ChatCitationListResponse(ChatBaseResponse):
    response_type: Literal["citation_list"] = "citation_list"
    citation_list: List[Citation]
