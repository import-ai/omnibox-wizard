import httpx

from tests.helper.fixture import base_url, namespace_id
from wizard.common.logger import get_logger

logger = get_logger("tests")


async def test_api(base_url: str, namespace_id: str):
    with httpx.Client(base_url=base_url) as client:
        json_response: dict = client.post("/task", json={
            "function": "html_to_markdown",
            "input": "<p>Hello World!</p>",
            "namespace_id": namespace_id
        }).raise_for_status().json()

        task_id: str = json_response["task_id"]
        assert len(task_id) == 22

        json_task: dict = client.get(f"/task/{task_id}").raise_for_status().json()
        assert json_task["task_id"] == task_id
        assert json_task["namespace_id"] == namespace_id
        assert json_task["create_time"] is not None
        assert json_task["start_time"] is None

        from wizard.worker import Worker
        worker = Worker(worker_id=0)
        task = await worker.fetch_and_claim_task()
        assert task is not None
        assert task.task_id == task_id

        json_task: dict = client.get(f"/task/{task_id}").raise_for_status().json()
        assert json_task["task_id"] == task_id
        assert json_task["namespace_id"] == namespace_id
        assert json_task["create_time"] is not None
        assert json_task["start_time"] is not None

        await worker.process_task(task)



