import httpx
import pytest

from omnibox_wizard.common import project_root
from omnibox_wizard.worker.config import WorkerConfig
from omnibox_wizard.worker.entity import Task
from omnibox_wizard.worker.worker import Worker
from tests.omnibox_wizard.helper.backend_client import BackendClient
from tests.omnibox_wizard.helper.fixture import worker_config, backend_client

fake_html: bool = True


@pytest.fixture(scope="function")
def html() -> str:
    if fake_html:
        html = "<html><header><title>Test Title</title></header><body><p>Hello World!</p></body></html>"
        yield html
    else:
        with project_root.open("tests/resources/files/index.html") as f:
            yield f.read()


@pytest.fixture(scope="function")
def task_id(backend_client: BackendClient, html: str) -> int:
    response: httpx.Response = backend_client.post("/api/v1/wizard/collect", json={
        "url": "https://example.com",
        "html": html,
        "title": "Test",
        "namespace_id": backend_client.namespace_id,
        "parentId": backend_client.private_root_id,
    })

    json_response: dict = response.json()
    assert response.status_code == 201, json_response

    task_id: int = json_response["task_id"]
    resource_id: int = json_response["resource_id"]
    assert isinstance(resource_id, str)

    return task_id


@pytest.fixture(scope="function")
async def worker(worker_config: WorkerConfig) -> Worker:
    worker = Worker(config=worker_config, worker_id=0)
    return worker


async def test_fetch_task(worker: Worker, task_id: int):
    task: Task = await worker.fetch_task()
    assert task.id == task_id


async def test_run_once(worker: Worker, task_id: int):
    await worker.run_once()
    await worker.run_once()
