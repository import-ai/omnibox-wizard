from abc import ABC, abstractmethod
from typing import Awaitable, Callable, TYPE_CHECKING

from omnibox_wizard.wizard.grimoire.client.resource_api import ResourceAPIClient
from omnibox_wizard.wizard.grimoire.entity.resource import ResourceInfo, ResourceToolResult
from omnibox_wizard.wizard.grimoire.entity.tools import (
    BaseResourceTool,
    PrivateSearchResourceType,
    Resource,
    ToolExecutorConfig,
)

if TYPE_CHECKING:
    from omnibox_wizard.wizard.grimoire.agent.tool_executor import ToolExecutor

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

    def get_function(self, tool: BaseResourceTool, tool_executor: "ToolExecutor" = None, **kwargs) -> ResourceFunction:
        async def _get_resources(cite_ids: list[str]) -> ResourceToolResult:
            # Support both ctx_N and numeric IDs
            resource_ids = [tool_executor.resolve_any_id(cid) for cid in cite_ids]
            result = await self.client.get_resources(tool.namespace_id, resource_ids)
            return result

        return _get_resources

    @classmethod
    def get_schema(cls) -> dict:
        return {
            "type": "function",
            "function": {
                "name": "get_resources",
                "display_name": {"zh": "读取资源", "en": "Get Resources"},
                "description": (
                    "Read the FULL content of resources by their citation IDs. "
                    "ALL resource types (doc, file, link) can be read - the system has already extracted/transcribed their content. "
                    "Use this AFTER filter_by_time/filter_by_tag/filter_by_keyword/get_children when you need detailed content. "
                    "Only request the resources you actually need - don't fetch all at once."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "cite_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of citation IDs (e.g., ['1', '2', '3']) from the context",
                        }
                    },
                    "required": ["cite_ids"],
                },
            },
        }


class GetChildrenHandler(BaseResourceHandler):
    """Handler for get_children tool."""

    def __init__(self, client: ResourceAPIClient):
        self.client = client

    def get_function(self, tool: BaseResourceTool, tool_executor: "ToolExecutor" = None, **kwargs) -> ResourceFunction:
        async def _get_children(cite_id: str, depth: int = 3) -> ResourceToolResult:
            # Support both ctx_N and numeric IDs
            resource_id = tool_executor.resolve_any_id(cite_id)
            result = await self.client.get_children(tool.namespace_id, resource_id, depth)
            # Set metadata_only mode to reduce token usage
            result.metadata_only = True
            return result

        return _get_children

    @classmethod
    def get_schema(cls) -> dict:
        return {
            "type": "function",
            "function": {
                "name": "get_children",
                "display_name": {"zh": "获取子目录", "en": "Get Children"},
                "description": (
                    "Get children directory tree of a resource. "
                    "Returns METADATA ONLY - use get_resources to read specific document contents. "
                    "Use this FIRST when user asks about folder contents, to summarize a folder, or to export folder data. "
                    "Returns a flat list of children resources."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "cite_id": {
                            "type": "string",
                            "description": "The folder's citation ID from available_resources",
                        },
                        "depth": {
                            "type": "integer",
                            "description": "Depth of the tree (1, 2, or 3, default: 3)",
                            "minimum": 1,
                            "maximum": 3,
                            "default": 3,
                        },
                    },
                    "required": ["cite_id"],
                },
            },
        }


class GetParentHandler(BaseResourceHandler):
    """Handler for get_parent tool."""

    def __init__(self, client: ResourceAPIClient):
        self.client = client

    def get_function(self, tool: BaseResourceTool, tool_executor: "ToolExecutor" = None, **kwargs) -> ResourceFunction:
        async def _get_parent(cite_id: str) -> ResourceToolResult:
            # Support both ctx_N and numeric IDs
            resource_id = tool_executor.resolve_any_id(cite_id)
            result = await self.client.get_parent(tool.namespace_id, resource_id)
            return result

        return _get_parent

    @classmethod
    def get_schema(cls) -> dict:
        return {
            "type": "function",
            "function": {
                "name": "get_parent",
                "display_name": {"zh": "获取上层文件夹", "en": "Get Parent Folder"},
                "description": (
                    "Get the parent folder of a document or subfolder. "
                    "Use this to navigate up the directory structure or find where a document is located."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "cite_id": {
                            "type": "string",
                            "description": "The citation ID of the document or folder",
                        }
                    },
                    "required": ["cite_id"],
                },
            },
        }


class FilterByTimeHandler(BaseResourceHandler):
    """Handler for filter_by_time tool."""

    def __init__(self, client: ResourceAPIClient):
        self.client = client

    def get_function(self, tool: BaseResourceTool, **kwargs) -> ResourceFunction:
        async def _filter_by_time(
            created_at_after: str, created_at_before: str
        ) -> ResourceToolResult:
            result = await self.client.filter_by_time(
                created_at_after=created_at_after,
                created_at_before=created_at_before,
                namespace_id=tool.namespace_id,
            )
            # Set metadata_only mode to reduce token usage
            result.metadata_only = True
            return result

        return _filter_by_time

    @classmethod
    def get_schema(cls) -> dict:
        return {
            "type": "function",
            "function": {
                "name": "filter_by_time",
                "display_name": {"zh": "按时间筛选", "en": "Filter by Time"},
                "description": (
                    "Find documents created or modified within a specific time range. "
                    "Returns METADATA ONLY (title, summary, tags) - use get_resources to fetch full content. "
                    "Use this when user asks about 'recent', 'today', 'this week', 'last month' documents."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "created_at_after": {
                            "type": "string",
                            "description": "Start time in ISO 8601 format (e.g., 2025-12-16T10:35:12.788Z)",
                        },
                        "created_at_before": {
                            "type": "string",
                            "description": "End time in ISO 8601 format (e.g., 2025-12-16T10:35:12.788Z)",
                        },
                    },
                    "required": ["created_at_after", "created_at_before"],
                },
            },
        }


class FilterByTagHandler(BaseResourceHandler):
    """Handler for filter_by_tag tool."""

    def __init__(self, client: ResourceAPIClient):
        self.client = client

    def get_function(self, tool: BaseResourceTool, **kwargs) -> ResourceFunction:
        async def _filter_by_tag(tags: list[str]) -> ResourceToolResult:
            result = await self.client.filter_by_tag(
                tags=tags,
                namespace_id=tool.namespace_id,
            )
            # Set metadata_only mode to reduce token usage
            result.metadata_only = True
            return result

        return _filter_by_tag

    @classmethod
    def get_schema(cls) -> dict:
        return {
            "type": "function",
            "function": {
                "name": "filter_by_tag",
                "display_name": {"zh": "按标签筛选", "en": "Filter by Tag"},
                "description": (
                    "Find documents with specific tags/labels. "
                    "Returns METADATA ONLY (title, summary, tags) - use get_resources to fetch full content. "
                    "Note: Only use if user explicitly mentions a tag, not for folder-based queries."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "tags": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of tag names to search for (e.g., ['tag1', 'tag2'])",
                        }
                    },
                    "required": ["tags"],
                },
            },
        }


class FilterByKeywordHandler(BaseResourceHandler):
    """Handler for filter_by_keyword tool."""

    def __init__(self, client: ResourceAPIClient):
        self.client = client

    def get_function(self, tool: BaseResourceTool, **kwargs) -> ResourceFunction:
        async def _filter_by_keyword(
            name_keywords: list[str] | None = None,
            content_keywords: list[str] | None = None,
        ) -> ResourceToolResult:
            result = await self.client.filter_by_keyword(
                namespace_id=tool.namespace_id,
                name_keywords=name_keywords,
                content_keywords=content_keywords,
            )
            # Set metadata_only mode to reduce token usage
            result.metadata_only = True
            return result

        return _filter_by_keyword

    @classmethod
    def get_schema(cls) -> dict:
        return {
            "type": "function",
            "function": {
                "name": "filter_by_keyword",
                "display_name": {"zh": "按关键词筛选", "en": "Filter by Keyword"},
                "description": (
                    "Filter documents by EXACT keyword matching in name/title or content fields. "
                    "Returns METADATA ONLY (title, summary, tags) - use get_resources to fetch full content. "
                    "Unlike private_search (semantic/fuzzy search), this performs substring matching. "
                    "Use filter_by_keyword when: "
                    "1) User asks for documents with specific words in their title/name (e.g., 'documents with meeting in the title') "
                    "2) User asks for documents containing specific terms in content (e.g., 'files containing budget') "
                    "Use private_search when: User asks for semantically related content (e.g., 'documents about project progress'). "
                    "At least one of name_keywords or content_keywords must be provided."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name_keywords": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": (
                                "Keywords for exact substring matching in document titles/names. "
                                "Example: ['meeting', 'report'] finds documents with these words in their title."
                            ),
                        },
                        "content_keywords": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": (
                                "Keywords for exact substring matching in document content. "
                                "Example: ['budget', 'Q1'] finds documents containing these terms."
                            ),
                        },
                    },
                    "required": [],
                },
            },
        }
