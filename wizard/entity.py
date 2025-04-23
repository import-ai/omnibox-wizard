from datetime import datetime

from pydantic import BaseModel, Field, ConfigDict
from pydantic.alias_generators import to_camel


class Base(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime | None = Field(default=None)
    deleted_at: datetime | None = Field(default=None)


class Task(Base):
    task_id: str = Field(alias="id")
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
