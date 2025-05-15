import json as jsonlib
import os
from functools import partial
from typing import Literal, Callable, TypedDict

from pydantic import BaseModel, Field

from common import project_root

ToolName = Literal["knowledge_search", "web_search"]


def get_tool_schema(tool_type: ToolName | str) -> dict:
    with project_root.open(os.path.join("resources/tool_schema", f'{tool_type}.json')) as f:
        schema: dict = jsonlib.load(f)
    return schema


TOOL_SCHEMA: dict[str, dict] = {
    tool: get_tool_schema(tool) for tool in os.listdir(project_root.path("resources/tool_schema"))
}


class Condition(BaseModel):
    namespace_id: str
    resource_ids: list[str] | None = Field(default=None)
    parent_ids: list[str] | None = Field(default=None)
    created_at: tuple[float, float] | None = Field(default=None)
    updated_at: tuple[float, float] | None = Field(default=None)


class ToolExecutorConfig(TypedDict):
    name: ToolName
    schema: dict
    func: Callable


class Tool(BaseModel):
    name: ToolName
    schema: dict

    def __init__(self, /, **kwargs):
        if "schema" not in kwargs:
            kwargs["schema"] = TOOL_SCHEMA[kwargs["type"]]
        super().__init__(**kwargs)

    def to_executor_config(self, func: Callable, /, **kwargs) -> ToolExecutorConfig:
        return ToolExecutorConfig(
            name=self.name,
            schema=self.schema,
            func=partial(func, **kwargs) if kwargs else func
        )


class KnowledgeTool(Tool, Condition):
    name: Literal["knowledge_search"] = "knowledge_search"

    def to_condition(self) -> Condition:
        return Condition(
            namespace_id=self.namespace_id,
            resource_ids=self.resource_ids,
            parent_ids=self.parent_ids,
            created_at=self.created_at,
            updated_at=self.updated_at
        )

    def to_executor_config(self, func: Callable, /, **kwargs) -> ToolExecutorConfig:
        return super().to_executor_config(func, **(kwargs | {"condition": self.to_condition()}))


class WebSearchTool(Tool):
    name: Literal["web_search"] = "web_search"
