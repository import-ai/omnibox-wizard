from functools import partial
from typing import Literal, Callable, TypedDict

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


class ToolExecutorConfig(TypedDict):
    name: ToolName
    schema: dict
    func: Callable


class Tool(BaseModel):
    name: ToolName
    schema: dict

    def to_executor_config(self, func: Callable, **kwargs) -> ToolExecutorConfig:
        return ToolExecutorConfig(
            name=self.name,
            schema=self.schema,
            func=partial(func, **kwargs) if kwargs else func
        )


class KnowledgeTool(Tool, Condition):
    name: Literal["knowledge_search"] = "knowledge_search"
    schema: dict = {
        "type": "function",
        "function": {
            "name": "knowledge_search",
            "description": (
                "Search the user's private knowledge base for relevant information matching the given query. "
                "Such as questions about their schedule, tasks, plans, meetings, files, notes, etc. "
                "Compared to other tools, this is the one you should prioritize using. "
                "You MUST call this tool if it's enabled."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The query to search for."
                    }
                },
                "required": [
                    "query"
                ]
            }
        }
    }

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
    schema: dict = {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Search the internet for the given query. "
                "If user's private knowledge base can't answer the question, "
                "you MUST call this function to retrieve information from the public internet."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The query to search for."
                    },
                    "page_number": {
                        "type": "integer",
                        "description": "The page number to search for."
                    }
                },
                "required": [
                    "query"
                ]
            }
        }
    }
