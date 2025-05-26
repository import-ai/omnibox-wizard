from pydantic import BaseModel, Field


class TitleRequest(BaseModel):
    text: str = Field(description="text to title")


class TitleResponse(BaseModel):
    title: str = Field(description="title of text")
