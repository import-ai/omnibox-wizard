from typing import List, Optional, Literal

from pydantic import BaseModel, Field

from wizard.grimoire.entity.retrieval import Citation


class InsertRequest(BaseModel):
    title: str = Field(description="Document title")
    content: str = Field(description="Document content")


class ChatRequest(BaseModel):
    session_id: str
    query: str
    namespace: str
    element_id_list: Optional[List[str]] = Field(default=None)


class ChatBaseResponse(BaseModel):
    response_type: Literal["delta", "citation", "citation_list"]


class ChatDeltaResponse(ChatBaseResponse):
    response_type: Literal["delta"] = "delta"
    delta: str


class ChatCitationListResponse(ChatBaseResponse):
    response_type: Literal["citation_list"] = "citation_list"
    citation_list: List[Citation]
