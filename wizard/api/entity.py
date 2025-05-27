from pydantic import BaseModel, Field


class CommonAITextRequest(BaseModel):
    text: str = Field(description="text to title")


class TitleResponse(BaseModel):
    title: str = Field(description="title of text")


class TagsResponse(BaseModel):
    tags: list[str] = Field(description="tags of text")
