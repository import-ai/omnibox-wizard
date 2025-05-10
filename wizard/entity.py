from datetime import datetime

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
    payload: dict | None = Field(default=None, description="Task payload, would pass through to the webhook")

    output: dict | None = None
    exception: dict | None = None

    started_at: datetime | None = None
    ended_at: datetime | None = None
    canceled_at: datetime | None = None
