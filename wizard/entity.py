from datetime import datetime

import shortuuid
from pydantic import BaseModel, Field, ConfigDict


class Base(BaseModel):
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    deleted_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class Task(Base):
    task_id: str = Field(default_factory=shortuuid.uuid)
    priority: int = Field(default=5)

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

    concurrency_threshold: int = Field(default=1, description="Concurrency threshold")
