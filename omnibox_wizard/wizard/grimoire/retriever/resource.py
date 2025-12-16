from abc import ABC, abstractmethod
from functools import partial
from typing import Awaitable, Callable

from omnibox_wizard.wizard.grimoire.client.resource_api import ResourceAPIClient
from omnibox_wizard.wizard.grimoire.entity.resource import ResourceToolResult
from omnibox_wizard.wizard.grimoire.entity.tools import (
    BaseResourceTool,
    ToolExecutorConfig,
)

ResourceFunction = Callable[..., Awaitable[ResourceToolResult]]


class BaseResourceHandler(ABC):
    """Base class for resource tool handlers."""

    def get_tool_executor_config(self, tool: BaseResourceTool, **kwargs) -> ToolExecutorConfig:
        return ToolExecutorConfig(
            name=self.name,  # Use handler's name, not tool's
            func=self.get_function(tool, **kwargs),
            schema=self.get_schema(),
        )

    @abstractmethod
    def get_function(self, tool: BaseResourceTool, **kwargs) -> ResourceFunction:
        raise NotImplementedError

    @classmethod
    @abstractmethod
    def get_schema(cls) -> dict:
        raise NotImplementedError

    @property
    def name(self) -> str:
        return self.get_schema()["function"]["name"]


class GetResourcesHandler(BaseResourceHandler):
    """Handler for get_resources tool."""

    def __init__(self, client: ResourceAPIClient):
        self.client = client

    def get_function(self, tool: BaseResourceTool, **kwargs) -> ResourceFunction:
        async def _get_resources(resource_ids: list[str]) -> ResourceToolResult:
            # Resolve short IDs to real IDs
            real_ids = tool.resolve_ids(resource_ids)
            return await self.client.get_resources(tool.namespace_id, real_ids)

        return _get_resources

    @classmethod
    def get_schema(cls) -> dict:
        return {
            "type": "function",
            "function": {
                "name": "get_resources",
                "description": (
                    "Read the full content of specific documents by their short IDs. "
                    "Use this AFTER you know which documents you need - typically after using get_children to list folder contents. "
                    "Example workflow: get_children(f1) -> see document list -> get_resources(['r1', 'r2']) to read content."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "resource_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of document short IDs (e.g., ['r1', 'r2']) to read",
                        }
                    },
                    "required": ["resource_ids"],
                },
            },
        }


class GetChildrenHandler(BaseResourceHandler):
    """Handler for get_children tool."""

    def __init__(self, client: ResourceAPIClient):
        self.client = client

    def get_function(self, tool: BaseResourceTool, **kwargs) -> ResourceFunction:
        async def _get_children(parent_id: str, depth: int = 3) -> ResourceToolResult:
            # Resolve short ID to real ID
            real_id = tool.resolve_id(parent_id)
            return await self.client.get_children(tool.namespace_id, real_id, depth)

        return _get_children

    @classmethod
    def get_schema(cls) -> dict:
        return {
            "type": "function",
            "function": {
                "name": "get_children",
                "description": (
                    "Get children directory tree of a resource. "
                    "Use this FIRST when user asks about folder contents, to summarize a folder, or to export folder data. "
                    "Returns a flat list of children resources. "
                    "After getting the list, use get_resources to read specific document contents."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "namespace_id": {
                            "type": "string",
                            "description": "The namespace ID from available_resources",
                        },
                        "resource_id": {
                            "type": "string",
                            "description": "The folder's short ID (e.g., 'f1', 'f2') from available_resources",
                        },
                        "depth": {
                            "type": "integer",
                            "description": "Depth of the tree (1, 2, or 3, default: 3)",
                            "minimum": 1,
                            "maximum": 3,
                            "default": 3,
                        },
                    },
                    "required": ["namespace_id", "resource_id"],
                },
            },
        }


class GetParentHandler(BaseResourceHandler):
    """Handler for get_parent tool."""

    def __init__(self, client: ResourceAPIClient):
        self.client = client

    def get_function(self, tool: BaseResourceTool, **kwargs) -> ResourceFunction:
        async def _get_parent(resource_id: str) -> ResourceToolResult:
            # Resolve short ID to real ID
            real_id = tool.resolve_id(resource_id)
            return await self.client.get_parent(tool.namespace_id, real_id)

        return _get_parent

    @classmethod
    def get_schema(cls) -> dict:
        return {
            "type": "function",
            "function": {
                "name": "get_parent",
                "description": (
                    "Get the parent folder of a document or subfolder. "
                    "Use this to navigate up the directory structure or find where a document is located."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "resource_id": {
                            "type": "string",
                            "description": "The short ID of the document or folder (e.g., 'r1', 'f1')",
                        }
                    },
                    "required": ["resource_id"],
                },
            },
        }


class FilterByTimeHandler(BaseResourceHandler):
    """Handler for filter_by_time tool."""

    def __init__(self, client: ResourceAPIClient):
        self.client = client

    def get_function(self, tool: BaseResourceTool, **kwargs) -> ResourceFunction:
        return partial(
            self.client.filter_by_time,
            namespace_id=tool.namespace_id,
        )

    @classmethod
    def get_schema(cls) -> dict:
        return {
            "type": "function",
            "function": {
                "name": "filter_by_time",
                "description": (
                    "Find documents created or modified within a specific time range. "
                    "Use this when user asks about 'recent', 'today', 'this week', 'last month' documents. "
                    "Returns a list of matching documents with their metadata."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "start_time": {
                            "type": "number",
                            "description": "Start time as Unix timestamp in seconds",
                        },
                        "end_time": {
                            "type": "number",
                            "description": "End time as Unix timestamp in seconds",
                        },
                    },
                    "required": ["start_time", "end_time"],
                },
            },
        }


class FilterByTagHandler(BaseResourceHandler):
    """Handler for filter_by_tag tool."""

    def __init__(self, client: ResourceAPIClient):
        self.client = client

    def get_function(self, tool: BaseResourceTool, **kwargs) -> ResourceFunction:
        return partial(
            self.client.filter_by_tag,
            namespace_id=tool.namespace_id,
        )

    @classmethod
    def get_schema(cls) -> dict:
        return {
            "type": "function",
            "function": {
                "name": "filter_by_tag",
                "description": (
                    "Find documents with a specific tag/label. "
                    "Use this when user asks about documents in a category or with a specific label. "
                    "Note: Only use if user explicitly mentions a tag, not for folder-based queries."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "tag": {
                            "type": "string",
                            "description": "The exact tag name to search for",
                        }
                    },
                    "required": ["tag"],
                },
            },
        }
