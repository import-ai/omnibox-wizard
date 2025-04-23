import httpx
import pytest
import shortuuid

from tests.helper.fixture import remote_config
from wizard.config import Config
from wizard.entity import Task
from wizard.wand.worker import Worker


class TestClient(httpx.Client):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.username: str = shortuuid.uuid()
        self.email: str = shortuuid.uuid() + "@example.com"
        self.namespace: str = shortuuid.uuid()

        response: httpx.Response = self.post("/internal/api/v1/signup", json={
            "username": self.username,
            "password": "password",
            "password_repeat": "password",
            "email": self.email
        })
        signup_result: dict = response.json()
        assert response.status_code == 201, signup_result

        self.user_id: int = signup_result["id"]
        self.access_token: str = signup_result["access_token"]
        assert self.username == signup_result["username"]

        self.headers["Authorization"] = f"Bearer {self.access_token}"

        response: httpx.Response = self.post("/api/v1/namespaces", json={"name": self.namespace})
        namespace_create_result: dict = response.json()
        assert response.status_code == 201, namespace_create_result
        self.namespace_id: str = namespace_create_result["id"]

    def __enter__(self) -> "TestClient":
        return self

    def __exit__(self, exc_type=None, exc_value=None, traceback=None):
        response: httpx.Response = self.delete(f"/api/v1/user/{self.user_id}")
        assert response.status_code == 200, response.json()


@pytest.fixture(scope="function")
def client(remote_config: Config) -> TestClient:
    with TestClient(base_url=remote_config.backend.base_url) as client:
        yield client


@pytest.fixture(scope="function")
def task_id(client: TestClient) -> int:
    response: httpx.Response = client.post("/api/v1/tasks/collect", json={
        "url": "https://example.com",
        "html": "<p>Hello World!</p>",
        "title": "Test",
        "namespace": client.namespace,
        "spaceType": "private"
    })

    json_response: dict = response.json()
    assert response.status_code == 201, json_response

    task_id: int = json_response["taskId"]
    resource_id: int = json_response["resourceId"]
    assert isinstance(resource_id, str)

    return task_id


@pytest.fixture(scope="function")
def worker(remote_config: Config) -> Worker:
    return Worker(config=remote_config, worker_id=0)


async def test_fetch_task(worker: Worker, task_id: int):
    task: Task = await worker.fetch_task()
    assert task.task_id == task_id


async def test_run_once(remote_config: Config, task_id: int):
    worker = Worker(config=remote_config, worker_id=0)
    await worker.run_once()
