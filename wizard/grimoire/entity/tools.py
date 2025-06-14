from enum import Enum
from functools import partial
from typing import List, Literal, Callable, TypedDict, Awaitable

from pydantic import BaseModel, Field

ToolName = Literal["private_search", "web_search"]


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

    def to_meili_where(self) -> List[str | List[str]]:
        and_clause: List[str | List[str]] = ['namespace_id = "{}"'.format(self.namespace_id)]
        or_clause: List[str] = []
        if self.resource_ids:
            or_clause.append(
                'chunk.resource_id IN [{}]'.format(", ".join('"{}"'.format(rid) for rid in self.resource_ids))
            )
        if self.parent_ids:
            or_clause.append(
                'chunk.parent_id IN [{}]'.format(", ".join('"{}"'.format(pid) for pid in self.parent_ids))
            )
        if or_clause:
            and_clause.append(or_clause)

        if self.created_at is not None:
            and_clause.append('chunk.created_at >= {}'.format(self.created_at[0]))
            and_clause.append('chunk.created_at <= {}'.format(self.created_at[1]))
        if self.updated_at is not None:
            and_clause.append('chunk.updated_at >= {}'.format(self.updated_at[0]))
            and_clause.append('chunk.updated_at <= {}'.format(self.updated_at[1]))

        return and_clause


class ToolExecutorConfig(TypedDict):
    name: str
    schema: dict
    func: Callable


class BaseTool(BaseModel):
    name: ToolName

    def to_func(self, func: Callable, **kwargs) -> Callable[..., Awaitable]:
        return partial(func, **kwargs) if kwargs else func


class PrivateSearchResourceType(str, Enum):
    RESOURCE = "resource"
    FOLDER = "folder"


class Resource(BaseModel):
    name: str
    id: str
    type: PrivateSearchResourceType
    child_ids: list[str] | None = Field(default=None, exclude=True)


class PrivateSearchTool(BaseTool):
    name: Literal["private_search"] = "private_search"
    namespace_id: str
    visible_resource_ids: list[str] = Field(
        exclude=True, default=None, description="Required in `AgentRequest`, excluded in `MessageDto`.")
    resources: list[Resource] = Field()

    def to_condition(self) -> Condition:
        if not self.visible_resource_ids:
            raise AssertionError("`visible_resource_ids` must be provided when export to `Condition`.")
        return Condition(
            namespace_id=self.namespace_id,
            resource_ids=self.visible_resource_ids,
        )

    def to_func(self, func: Callable, /, **kwargs) -> Callable[..., Awaitable]:
        return super().to_func(func, **(kwargs | {"condition": self.to_condition()}))


class WebSearchTool(BaseTool):
    name: Literal["web_search"] = "web_search"
