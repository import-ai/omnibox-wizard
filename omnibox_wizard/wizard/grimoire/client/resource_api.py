import httpx
from opentelemetry import propagate, trace

from omnibox_wizard.wizard.grimoire.entity.resource import (
    ResourceInfo,
    ResourceToolResult,
)
from omnibox_wizard.worker.config import BackendConfig

tracer = trace.get_tracer(__name__)

DEFAULT_TIMEOUT = 30


class ResourceAPIClient:
    """Client for calling backend Resource APIs."""

    def __init__(self, config: BackendConfig):
        self.config = config

    @tracer.start_as_current_span("ResourceAPIClient._request")
    async def _request(self, method: str, path: str, **kwargs) -> dict:
        """Make HTTP request to backend API."""
        headers = {}
        propagate.inject(headers)
        span = trace.get_current_span()
        span.set_attributes({
            "base_url":f"{self.config.base_url}"
            }
        )
        async with httpx.AsyncClient(
            base_url=self.config.base_url, timeout=DEFAULT_TIMEOUT
        ) as client:
            response = await client.request(method, path, headers=headers, **kwargs)
            response.raise_for_status()
            return response.json()

    @tracer.start_as_current_span("ResourceAPIClient.get_resources")
    async def get_resources(
        self, namespace_id: str, resource_ids: list[str]
    ) -> ResourceToolResult:
        """Get full content of one or more resources.

        Args:
            namespace_id: Namespace ID for the resources.
            resource_ids: List of resource IDs to retrieve.

        Returns:
            ResourceToolResult containing list of resources with full content.
            Each resource includes a 'path' field containing all parent resources.
        """
        try:
            ids_param = ",".join(resource_ids)
            data = await self._request(
                "GET",
                f"/internal/api/v1/namespaces/{namespace_id}/resources",
                params={"id": ids_param},
            )
            return ResourceToolResult(
                success=True,
                data=[ResourceInfo(**item) for item in data],
            )
        except Exception as e:
            return ResourceToolResult(success=False, error=str(e))

    @tracer.start_as_current_span("ResourceAPIClient.get_children")
    async def get_children(
        self, namespace_id: str, resource_id: str, depth: int = 3
    ) -> ResourceToolResult:
        """Get children directory tree of a resource.

        Args:
            namespace_id: Namespace ID for the resource.
            resource_id: ID of the parent resource.
            depth: Depth of the tree (1, 2, or 3, default: 3).

        Returns:
            ResourceToolResult containing flat list of children resources.
            Use 'parent_id' field to construct tree structure.
        """
        try:
            span = trace.get_current_span()
            span.set_attributes({
                "base_url":f"{self.config.base_url}"
                }
            )
            data = await self._request(
                "GET",
                f"/internal/api/v1/namespaces/{namespace_id}/resources/{resource_id}/children",
                params={"depth": depth},
            )
            return ResourceToolResult(
                success=True,
                data=[ResourceInfo(**item) for item in data],
            )
        except Exception as e:
            return ResourceToolResult(success=False, error=str(e))

    @tracer.start_as_current_span("ResourceAPIClient.get_parent")
    async def get_parent(
        self, namespace_id: str, resource_id: str
    ) -> ResourceToolResult:
        """Get the parent resource of a given resource.

        Args:
            namespace_id: Namespace ID for the resource.
            resource_id: ID of the resource to get parent for.

        Returns:
            ResourceToolResult containing the parent resource.
        """
        try:
            data = await self._request(
                "GET",
                f"/internal/api/v1/namespaces/{namespace_id}/resources/{resource_id}/parent",
            )
            return ResourceToolResult(
                success=True,
                data=[ResourceInfo(**data)] if data else [],
            )
        except Exception as e:
            return ResourceToolResult(success=False, error=str(e))

    @tracer.start_as_current_span("ResourceAPIClient.filter_by_time")
    async def filter_by_time(
        self,
        created_at_after: str,
        created_at_before: str,
        namespace_id: str,
    ) -> ResourceToolResult:
        """Filter resources by creation time.

        Args:
            created_at_after: Start time in ISO 8601 format (e.g., 2025-12-16T10:35:12.788Z).
            created_at_before: End time in ISO 8601 format (e.g., 2025-12-16T10:35:12.788Z).
            namespace_id: Namespace ID for filtering.

        Returns:
            ResourceToolResult containing filtered resources.
        """
        try:
            data = await self._request(
                "GET",
                f"/internal/api/v1/namespaces/{namespace_id}/resources",
                params={
                    "createdAtAfter": created_at_after,
                    "createdAtBefore": created_at_before,
                },
            )
            return ResourceToolResult(
                success=True,
                data=[ResourceInfo(**item) for item in data],
            )
        except Exception as e:
            return ResourceToolResult(success=False, error=str(e))

    @tracer.start_as_current_span("ResourceAPIClient.filter_by_tag")
    async def filter_by_tag(
        self,
        tags: list[str],
        namespace_id: str,
    ) -> ResourceToolResult:
        """Filter resources by tag.

        Args:
            tag: Tag to filter by.
            namespace_id: Namespace ID for filtering.

        Returns:
            ResourceToolResult containing filtered resources.
        """
        try:
            tag_param = ",".join(tags)
            data = await self._request(
                "GET",
                f"/internal/api/v1/namespaces/{namespace_id}/resources",
                params={"tag": tag_param}
            )
            return ResourceToolResult(
                success=True,
                data=[ResourceInfo(**item) for item in data],
            )
        except Exception as e:
            return ResourceToolResult(success=False, error=str(e))
