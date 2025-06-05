from functools import partial
from typing import Literal, Callable, TypedDict, Awaitable

from pydantic import BaseModel, Field

ToolName = Literal["knowledge_search", "web_search"]


class Condition(BaseModel):
    namespace_id: str
    resource_ids: list[str] | None = Field(default=None)
    parent_ids: list[str] | None = Field(default=None)
    created_at: tuple[float, float] | None = Field(default=None)
    updated_at: tuple[float, float] | None = Field(default=None)

    def to_chromadb_where(self) -> dict | None:
        and_clause = []
        or_clause = []
        if self.resource_ids:
            or_clause.append({"resource_id": {"$in": self.resource_ids}})
        if self.parent_ids:
            or_clause.append({"parent_id": {"$in": self.parent_ids}})
        if or_clause:
            and_clause.append({"$or": or_clause} if len(or_clause) > 1 else or_clause[0])

        if self.created_at is not None:
            and_clause.append({"created_at": {"$gte": self.created_at[0], "$lte": self.created_at[1]}})
        if self.updated_at is not None:
            and_clause.append({"updated_at": {"$gte": self.updated_at[0], "$lte": self.updated_at[1]}})

        if and_clause:
            where = {"$and": and_clause} if len(and_clause) > 1 else and_clause[0]
        else:
            where = None
        return where


class FunctionMeta(TypedDict):
    name: ToolName
    description: str
    func: Callable[..., Awaitable]


class ToolExecutorConfig(TypedDict):
    schema: dict
    func: Callable


class BaseTool(BaseModel):
    name: ToolName

    def to_func(self, func: Callable, **kwargs) -> Callable[..., Awaitable]:
        return partial(func, **kwargs) if kwargs else func


class KnowledgeTool(BaseTool, Condition):
    name: Literal["knowledge_search"] = "knowledge_search"

    def to_condition(self) -> Condition:
        return Condition(
            namespace_id=self.namespace_id,
            resource_ids=self.resource_ids,
            parent_ids=self.parent_ids,
            created_at=self.created_at,
            updated_at=self.updated_at
        )

    def to_func(self, func: Callable, /, **kwargs) -> Callable[..., Awaitable]:
        return super().to_func(func, **(kwargs | {"condition": self.to_condition()}))


class WebSearchTool(BaseTool):
    name: Literal["web_search"] = "web_search"
