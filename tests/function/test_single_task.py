from tests.helper.fixture import config
from wizard.config import Config
from wizard.entity import Task
from wizard.wand.worker import Worker
import httpx
import pytest


@pytest.mark.parametrize("task_id", ["UqZHmUr28DyZRQ4y5SxGji"])
async def test_single_task(config: Config, task_id: str):
    worker = Worker(config, worker_id=0)
    await worker.async_init()
    with httpx.Client(base_url=config.backend.base_url) as client:
        httpx_response: httpx.Response = client.get(f"/api/v1/tasks/{task_id}")
        httpx_response.raise_for_status()
        json_response: dict = httpx_response.json()
        task = Task.model_validate(json_response)
    response = await worker.process_task(task, worker.get_trace_info(task))
    print(response)

