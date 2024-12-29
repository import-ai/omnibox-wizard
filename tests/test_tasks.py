import httpx

from tests.helper.fixture import client
from common.logger import get_logger

logger = get_logger("tests")


async def test_tasks(client: httpx.Client):
    namespace_id: str = "foo"
    user_id: str = "bar"

    json_response: dict = client.post("/api/v1/tasks", json={
        "function": "html_to_markdown",
        "input": {
            "html": "<p>Hello World!</p>",
            "url": "foo"
        },
        "namespace_id": namespace_id,
        "user_id": user_id
    }).raise_for_status().json()

    task_id: str = json_response["task_id"]
    assert len(task_id) == 22

    json_task: dict = client.get(f"/api/v1/tasks/{task_id}").raise_for_status().json()
    assert json_task["task_id"] == task_id
    assert json_task["namespace_id"] == namespace_id
    assert json_task["created_at"] is not None
    assert json_task.get("started_at", None) is None

    from wizard.wand.worker import Worker
    worker = Worker(worker_id=0)
    task = await worker.fetch_and_claim_task()
    assert task is not None
    assert task.task_id == task_id

    json_task: dict = client.get(f"/api/v1/tasks/{task_id}").raise_for_status().json()
    assert json_task["task_id"] == task_id
    assert json_task["namespace_id"] == namespace_id
    assert json_task["created_at"] is not None
    assert json_task["started_at"] is not None
    assert json_task.get("ended_at", None) is None

    await worker.process_task(task)

    json_task: dict = client.get(f"/api/v1/tasks/{task_id}").raise_for_status().json()
    assert json_task["task_id"] == task_id
    assert json_task["namespace_id"] == namespace_id
    assert json_task["created_at"] is not None
    assert json_task["started_at"] is not None
    assert json_task["ended_at"] is not None
    assert json_task["output"]["markdown"] == "Hello World!"

    logger.info(json_task)
