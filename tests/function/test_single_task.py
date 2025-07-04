import httpx
import pytest

from tests.helper.fixture import worker_config
from omnibox_wizard.wizard.config import WorkerConfig
from omnibox_wizard.wizard.entity import Task
from omnibox_wizard.wizard.wand.worker import Worker


@pytest.mark.parametrize("task_id", ["UqZHmUr28DyZRQ4y5SxGji"])
async def test_single_task(worker_config: WorkerConfig, task_id: str):
    worker = Worker(worker_config, worker_id=0)
    with httpx.Client(base_url=worker_config.backend.base_url) as client:
        httpx_response: httpx.Response = client.get(f"/api/v1/tasks/{task_id}")
        httpx_response.raise_for_status()
        json_response: dict = httpx_response.json()
        task = Task.model_validate(json_response)
    response = await worker.process_task(task, worker.get_trace_info(task))
    print(response)
