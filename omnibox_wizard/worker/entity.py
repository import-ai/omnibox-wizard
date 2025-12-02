import base64
from datetime import datetime
from typing import BinaryIO

from pydantic import BaseModel, Field


class Base(BaseModel):
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime | None = Field(default=None)
    deleted_at: datetime | None = Field(default=None)


class Task(Base):
    id: str
    priority: int

    namespace_id: str
    user_id: str

    function: str
    input: dict
    payload: dict | None = Field(
        default=None, description="Task payload, would pass through to the webhook"
    )

    output: dict | None = None
    exception: dict | None = None

    started_at: datetime | None = None
    ended_at: datetime | None = None
    canceled_at: datetime | None = None


class Image(BaseModel):
    name: str = Field(default=None)
    link: str
    data: str = Field(description="Base64 encoded image data")
    mimetype: str = Field(examples=["image/jpeg", "image/png", "image/gif"])

    def dumps(self) -> str:
        return f"data:{self.mimetype};base64,{self.data}"

    def dump(self, f: BinaryIO) -> None:
        f.write(base64.b64decode(self.data))


class GeneratedContent(BaseModel):
    title: str | None = Field(default=None)
    markdown: str
    images: list[Image] | None = Field(default=None)


class Message(BaseModel):
    task_id: str
    function: str
