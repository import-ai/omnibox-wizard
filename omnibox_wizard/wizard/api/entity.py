from typing import Literal

from pydantic import BaseModel, Field

from wizard_common.grimoire.entity.index_record import IndexRecord, IndexRecordType


class CommonAITextRequest(BaseModel):
    text: str = Field(description="text to title")
    lang: Literal["简体中文", "English"] = Field(
        default="简体中文", description="Language of the response."
    )


class TitleResponse(BaseModel):
    title: str = Field(description="title of text")


class TagsResponse(BaseModel):
    tags: list[str] = Field(description="tags of text")


class SearchRequest(BaseModel):
    query: str = Field(description="search query")
    namespace_id: str = Field(description="namespace id to search in")
    user_id: str | None = Field(description="user id")
    type: IndexRecordType | None = Field(default=None, description="type of record")
    offset: int = Field(default=0, description="offset")
    limit: int = Field(default=20, description="maximum number of records")


class SearchResponse(BaseModel):
    records: list[IndexRecord] = Field(description="search results")


class UpsertWeaviateResourceRequest(BaseModel):
    namespace_id: str
    resource_id: str
    parent_id: str
    title: str = ""
    content: str = ""
    resource_tag_ids: list[str] = Field(default_factory=list)
    resource_tag_names: list[str] = Field(default_factory=list)


class UpsertWeaviateOpenAIMessage(BaseModel):
    role: str
    content: str


class UpsertWeaviateMessage(BaseModel):
    conversation_id: str
    message_id: str
    message: UpsertWeaviateOpenAIMessage


class UpsertWeaviateMessageRequest(BaseModel):
    namespace_id: str
    user_id: str
    message: UpsertWeaviateMessage
