import base64
from datetime import datetime
from typing import BinaryIO
from enum import StrEnum

from pydantic import BaseModel, Field


class Base(BaseModel):
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime | None = Field(default=None)
    deleted_at: datetime | None = Field(default=None)


class TaskFunction(StrEnum):
    COLLECT = "collect"
    COLLECT_URL = "collect_url"
    UPSERT_INDEX = "upsert_index"
    DELETE_INDEX = "delete_index"
    FILE_READER = "file_reader"
    UPSERT_MESSAGE_INDEX = "upsert_message_index"
    DELETE_CONVERSATION = "delete_conversation"
    EXTRACT_TAGS = "extract_tags"
    GENERATE_TITLE = "generate_title"


class NextTaskResponseDto(BaseModel):
    function: TaskFunction
    input: dict
    payload: dict | None = Field(default=None)
    priority: int | None = Field(default=None)


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    FINISHED = "finished"
    ERROR = "error"
    CANCELED = "canceled"
    TIMEOUT = "timeout"


class TaskCallbackRequestDto(BaseModel):
    id: str
    exception: dict | None = Field(default=None)
    output: dict | None = Field(default=None)
    status: TaskStatus | None = Field(default=None)


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
    status: str | None = None

    def create_next_task(self, function: TaskFunction, i: dict):
        return NextTaskResponseDto(
            input=i, function=function, payload=self.payload, priority=self.priority
        )


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
    meta: dict[str, str] = Field(default_factory=dict)
