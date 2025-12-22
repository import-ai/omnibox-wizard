from abc import ABC, abstractmethod
from typing import Awaitable, Callable

from omnibox_wizard.wizard.grimoire.client.resource_api import ResourceAPIClient
from omnibox_wizard.wizard.grimoire.entity.resource import ResourceInfo, ResourceToolResult
from omnibox_wizard.wizard.grimoire.entity.tools import (
    BaseResourceTool,
    PrivateSearchResourceType,
    Resource,
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

    def assign_short_ids_to_resources(
        self, tool: BaseResourceTool, resources: list[ResourceInfo] | ResourceInfo
    ) -> None:
        """Add resources to visible_resources and assign short IDs.

        This method:
        1. Adds new resources to tool.visible_resources
        2. Assigns short_id to each ResourceInfo for LLM display
        """
        # Handle single resource case
        if isinstance(resources, ResourceInfo):
            resources = [resources]

        if tool.visible_resources is None:
            tool.visible_resources = []

        # Build existing ID set for quick lookup
        existing_ids = {r.id for r in tool.visible_resources}

        # Count existing short IDs to continue numbering
        resource_counter = sum(
            1 for r in tool.visible_resources
            if r.type == PrivateSearchResourceType.RESOURCE
        )
        folder_counter = sum(
            1 for r in tool.visible_resources
            if r.type == PrivateSearchResourceType.FOLDER
        )

        for resource in resources:
            # If already exists, just find and assign the short_id
            if resource.id in existing_ids:
                resource.short_id = self._find_short_id(tool, resource.id)
                continue

            # Determine resource type and assign short_id
            if resource.resource_type == "folder":
                folder_counter += 1
                short_id = f"f{folder_counter}"
                res_type = PrivateSearchResourceType.FOLDER
            else:
                resource_counter += 1
                short_id = f"r{resource_counter}"
                res_type = PrivateSearchResourceType.RESOURCE

            # Assign short_id to the ResourceInfo for LLM display
            resource.short_id = short_id

            # Add to visible_resources for future resolution
            tool.visible_resources.append(Resource(
                id=resource.id,
                name=resource.name,
                type=res_type,
            ))
            existing_ids.add(resource.id)

    def _find_short_id(self, tool: BaseResourceTool, resource_id: str) -> str | None:
        """Find the short_id for an existing resource."""
        if not tool.visible_resources:
            return None

        resource_counter = 0
        folder_counter = 0

        for resource in tool.visible_resources:
            if resource.type == PrivateSearchResourceType.FOLDER:
                folder_counter += 1
                short_id = f"f{folder_counter}"
            else:
                resource_counter += 1
                short_id = f"r{resource_counter}"

            if resource.id == resource_id:
                return short_id

        return None


class GetResourcesHandler(BaseResourceHandler):
    """Handler for get_resources tool."""

    def __init__(self, client: ResourceAPIClient):
        self.client = client

    def get_function(self, tool: BaseResourceTool, **kwargs) -> ResourceFunction:
        async def _get_resources(resource_ids: list[str]) -> ResourceToolResult:
            # Resolve short IDs to real IDs
            real_ids = tool.resolve_ids(resource_ids)
            result = await self.client.get_resources(tool.namespace_id, real_ids)

            if result.success and result.data:
                # Assign short IDs to returned resources for consistency
                self.assign_short_ids_to_resources(tool, result.data)

            return result

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
        async def _get_children(resource_id: str, depth: int = 3) -> ResourceToolResult:
            # Resolve short ID to real ID
            real_id = tool.resolve_id(resource_id)
            result = await self.client.get_children(tool.namespace_id, real_id, depth)

            if result.success and result.data:
                # Add returned children to visible_resources and assign short IDs
                self.assign_short_ids_to_resources(tool, result.data)
                doc_ids = [r.short_id for r in result.data]
                result.hint = (
                    f"To read document contents, call get_resources with short IDs: {doc_ids}. "
                )

            return result

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
                    "required": ["resource_id"],
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
            result = await self.client.get_parent(tool.namespace_id, real_id)

            if result.success and result.data:
                # Add returned parent to visible_resources and assign short IDs
                self.assign_short_ids_to_resources(tool, result.data)

            return result

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
        async def _filter_by_time(
            created_at_after: str, created_at_before: str
        ) -> ResourceToolResult:
            result = await self.client.filter_by_time(
                created_at_after=created_at_after,
                created_at_before=created_at_before,
                namespace_id=tool.namespace_id,
            )

            if result.success and result.data:
                # Add returned resources to visible_resources and assign short IDs
                self.assign_short_ids_to_resources(tool, result.data)

                # Generate hint for LLM: list readable documents with their short IDs
                readable_docs = [
                    r for r in result.data
                    if r.resource_type == "doc" and r.short_id
                ]
                if readable_docs:
                    doc_ids = [r.short_id for r in readable_docs]
                    result.hint = (
                        f"To read document contents, call get_resources with short IDs: {doc_ids}. "
                        f"Only 'doc' type can be read."
                    )

            return result

        return _filter_by_time

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

            if result.success and result.data:
                # Add returned resources to visible_resources and assign short IDs
                self.assign_short_ids_to_resources(tool, result.data)

                # Generate hint for LLM: list readable documents with their short IDs
                readable_docs = [
                    r for r in result.data
                    if r.resource_type == "doc" and r.short_id
                ]
                if readable_docs:
                    doc_ids = [r.short_id for r in readable_docs]
                    result.hint = (
                        f"To read document contents, call get_resources with short IDs: {doc_ids}. "
                        f"Only 'doc' type can be read."
                    )

            return result

        return _filter_by_tag

    @classmethod
    def get_schema(cls) -> dict:
        return {
            "type": "function",
            "function": {
                "name": "filter_by_tag",
                "description": (
                    "Find documents with specific tags/labels. "
                    "Use this when user asks about documents in a category or with specific labels. "
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
