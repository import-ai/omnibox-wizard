import httpx
from opentelemetry import trace
from pydantic import BaseModel, Field

tracer = trace.get_tracer(__name__)


class VisibleResourcesResponseDto(BaseModel):
    resource_ids: list[str] = Field(default_factory=list)


class BackendVisibleBaseClient:
    async def filter_visible_resource_ids(self, resource_ids: list[str]) -> list[str]:
        return list(dict.fromkeys(resource_ids))


class BackendVisibleClient(BackendVisibleBaseClient):
    def __init__(self, base_url: str, user_id: str, namespace_id: str):
        self.base_url = base_url.rstrip("/")
        self.user_id = user_id
        self.namespace_id = namespace_id

    @tracer.start_as_current_span("BackendVisibleClient.filter_visible_resource_ids")
    async def filter_visible_resource_ids(self, resource_ids: list[str]) -> list[str]:
        unique_ids = list(dict.fromkeys(resource_ids))
        trace.get_current_span().set_attribute("len(resource_ids)", len(unique_ids))
        if not unique_ids:
            return []
        async with httpx.AsyncClient(
            base_url=f"{self.base_url}/internal/api/v1/namespaces/{self.namespace_id}",
            headers={"X-User-ID": self.user_id},
            timeout=httpx.Timeout(10.0, connect=5.0),
        ) as client:
            httpx_response = await client.post(
                "/resources/visible",
                json={"resource_ids": unique_ids},
            )
            httpx_response.raise_for_status()
        return VisibleResourcesResponseDto.model_validate(
            httpx_response.json()
        ).resource_ids
