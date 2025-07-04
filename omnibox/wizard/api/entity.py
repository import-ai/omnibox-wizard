from pydantic import BaseModel, Field

from omnibox.wizard.grimoire.entity.index_record import IndexRecord, IndexRecordType


class CommonAITextRequest(BaseModel):
    text: str = Field(description="text to title")


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
