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

    async def _request(self, method: str, path: str, **kwargs) -> dict:
        """Make HTTP request to backend API."""
        headers = {}
        propagate.inject(headers)
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

    @tracer.start_as_current_span("ResourceAPIClient.filter_by_time")
    async def filter_by_time(
        self,
        start_time: float,
        end_time: float,
        user_id: str,
        namespace_id: str,
        parent_id: str | None = None,
    ) -> ResourceToolResult:
        """Filter resources by creation time.

        Args:
            start_time: Start time as Unix timestamp (seconds).
            end_time: End time as Unix timestamp (seconds).
            user_id: User ID for filtering.
            namespace_id: Namespace ID for filtering.
            parent_id: Optional parent folder ID to limit search scope.

        Returns:
            ResourceToolResult containing filtered resources.
        """
        try:
            payload = {
                "start_time": start_time,
                "end_time": end_time,
                "user_id": user_id,
                "namespace_id": namespace_id,
            }
            if parent_id:
                payload["parent_id"] = parent_id

            data = await self._request(
                "POST", "/api/resources/filter/time", json=payload
            )
            return ResourceToolResult(
                success=True,
                data=[ResourceInfo(**item) for item in data.get("resources", [])],
            )
        except Exception as e:
            return ResourceToolResult(success=False, error=str(e))

    @tracer.start_as_current_span("ResourceAPIClient.filter_by_tag")
    async def filter_by_tag(
        self,
        tag: str,
        user_id: str,
        namespace_id: str,
        parent_id: str | None = None,
    ) -> ResourceToolResult:
        """Filter resources by tag.

        Args:
            tag: Tag to filter by.
            user_id: User ID for filtering.
            namespace_id: Namespace ID for filtering.
            parent_id: Optional parent folder ID to limit search scope.

        Returns:
            ResourceToolResult containing filtered resources.
        """
        try:
            payload = {
                "tag": tag,
                "user_id": user_id,
                "namespace_id": namespace_id,
            }
            if parent_id:
                payload["parent_id"] = parent_id

            data = await self._request(
                "POST", "/api/resources/filter/tag", json=payload
            )
            return ResourceToolResult(
                success=True,
                data=[ResourceInfo(**item) for item in data.get("resources", [])],
            )
        except Exception as e:
            return ResourceToolResult(success=False, error=str(e))
