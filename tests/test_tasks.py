import os

import httpx

from common.logger import get_logger
from common.trace_info import TraceInfo
from tests.helper.fixture import client, worker_config
from tests.helper.fixture import trace_info
from wizard.config import WorkerConfig, ENV_PREFIX
from wizard.wand.worker import Worker

logger = get_logger("tests")


async def test_tasks(client: httpx.Client, worker_config: WorkerConfig, trace_info: TraceInfo):
    enable_callback: bool = os.environ.get(f"{ENV_PREFIX}_TESTS_ENABLE_WORKER_CALLBACK", "false").lower() == "true"
    namespace_id: str = "foo"
    user_id: str = "bar"

    task_ids: [str] = []

    for i in range(3):
        json_response: dict = client.post("/api/v1/tasks", json={
            "function": "collect",
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

        task_ids.append(task_id)

        logger.info({"task_created": json_task, "round": i})

    worker = Worker(config=worker_config, worker_id=0)
    await worker.async_init()

    for i in range(3):
        task_id = task_ids[i]
        task = await worker.fetch_task()
        assert task is not None
        assert task.task_id == task_id

        json_task: dict = client.get(f"/api/v1/tasks/{task_id}").raise_for_status().json()
        assert json_task["task_id"] == task_id
        assert json_task["namespace_id"] == namespace_id
        assert json_task["created_at"] is not None
        assert json_task["started_at"] is not None
        assert json_task.get("ended_at", None) is None

        task = await worker.process_task(task, trace_info)

        json_task: dict = client.get(f"/api/v1/tasks/{task_id}").raise_for_status().json()
        assert json_task["task_id"] == task_id
        assert json_task["namespace_id"] == namespace_id
        assert json_task["created_at"] is not None
        assert json_task["started_at"] is not None
        assert json_task["ended_at"] is not None
        assert json_task["output"]["markdown"] == "Hello World!"

        if enable_callback:
            await worker.callback(task, trace_info)

        logger.info({"task": json_task, "round": i})
