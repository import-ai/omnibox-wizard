import httpx
from wizard_common.worker.entity import Task


class InsufficientQuotaError(Exception):
    def __init__(self, details: dict):
        self.details = details
        self.message = details.get("code", "INSUFFICIENT_CREDITS")
        super().__init__(self.message)


async def check_task_quota(base_url: str, task: Task, quota: dict) -> dict:
    async with httpx.AsyncClient(
        base_url=base_url, transport=httpx.AsyncHTTPTransport(retries=3)
    ) as client:
        response = await client.post(
            f"/internal/api/v1/wizard/tasks/{task.id}/check",
            json={"task": task.model_dump(mode="json"), "quota": quota},
        )
        response.raise_for_status()
        result = response.json()
        if result.get("code"):
            raise InsufficientQuotaError(result)
        return result
