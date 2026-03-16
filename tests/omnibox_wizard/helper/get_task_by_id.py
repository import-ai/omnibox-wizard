import os

import httpx

from wizard_common.worker.entity import Task

backend_env_key: str = "OBW_BACKEND_BASE_URL"


async def get_task_by_id(task_id: str) -> Task:
    backend_url = os.environ[backend_env_key]
    async with httpx.AsyncClient(base_url=backend_url) as client:
        httpx_response: httpx.Response = await client.get(
            f"/internal/api/v1/wizard/tasks/{task_id}"
        )
        httpx_response.raise_for_status()
        json_response: dict = httpx_response.json()
        task = Task.model_validate(json_response)
    return task
