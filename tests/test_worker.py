import httpx
import pytest

from common import project_root
from tests.helper.backend_client import BackendClient
from tests.helper.fixture import worker_config, backend_client
from wizard.config import WorkerConfig
from wizard.entity import Task
from wizard.wand.worker import Worker

fake_html: bool = False


@pytest.fixture(scope="function")
def html() -> str:
    with project_root.open("tests/resources/files/index.html") as f:
        yield f.read()


@pytest.fixture(scope="function")
def task_id(backend_client: BackendClient, html: str) -> int:
    if fake_html:
        html = "<html><header><title>Test Title</title></header><body><p>Hello World!</p></body></html>"

    response: httpx.Response = backend_client.post("/api/v1/wizard/collect", json={
        "url": "https://example.com",
        "html": html,
        "title": "Test",
        "namespace_id": backend_client.namespace_id,
        "space_type": "private"
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
