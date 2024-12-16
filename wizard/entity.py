from datetime import datetime
from typing import Optional, Dict

import shortuuid
from pydantic import BaseModel, Field, ConfigDict


class Task(BaseModel):
    task_id: str = Field(default_factory=shortuuid.uuid)
    priority: int = Field(default=5)
    namespace_id: str
    function: str
    input: Dict
    create_time: datetime = Field(default_factory=datetime.now)
    output: Optional[Dict] = None
    exception: Optional[Dict] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    cancel_time: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)
