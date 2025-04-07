import json
from typing import Iterator, List

import httpx
import pytest

from tests.helper.fixture import client, worker
from wizard.entity import Task
from wizard.grimoire.entity.api import ChatRequest
from wizard.wand.worker import Worker


def assert_stream(stream: Iterator[str]):
    for each in stream:
        response = json.loads(each)
        response_type = response["response_type"]
        assert response_type != "error"
        if response_type == "delta":
            print(response["delta"], end="", flush=True)
        elif response_type == "citation_list":
            print("\n".join(["", "-" * 32, json.dumps(response["citation_list"], ensure_ascii=False)]))
        elif response_type == "done":
            pass
        else:
            raise RuntimeError(f"response_type: {response['response_type']}")


def api_stream(client: httpx.Client, request: ChatRequest) -> Iterator[str]:
    with client.stream("POST", "/api/v1/grimoire/stream", json=request.model_dump()) as response:
        if response.status_code != 200:
            raise Exception(f"{response.status_code} {response.text}")
        for line in response.iter_lines():
            if line.startswith("data: "):
                yield line[6:]


async def add_index(
        client: httpx.Client,
        worker: Worker,
        title: str,
        content: str,
        namespace_id: str,
        space_type: str,
        resource_id: str,
        parent_id: str,
        user_id: str
):
    json_response: dict = client.post("/api/v1/tasks", json={
        "function": "create_or_update_index",
        "input": {
            "title": title,
            "content": content,
            "meta_info": {
                "user_id": user_id,
                "space_type": space_type,
                "resource_id": resource_id,
                "parent_id": parent_id,
            },
        },
        "namespace_id": namespace_id,
        "user_id": user_id
    }).raise_for_status().json()

    task_id = json_response["task_id"]

    task: Task = await worker.fetch_task()
    await worker.process_task(task)

    json_task: dict = client.get(f"/api/v1/tasks/{task_id}").raise_for_status().json()
    assert json_task["task_id"] == task_id
    assert json_task["namespace_id"] == namespace_id
    assert json_task["created_at"] is not None
    assert json_task["started_at"] is not None
    assert json_task["ended_at"] is not None

    output = json_task["output"]
    assert output["success"] is True


create_test_case = ("resource_id, parent_id, title, content", [
    ("r_id_a0", "p_id_0", "下周计划", "+ 9:00 起床\n+ 10:00 上班"),
    ("r_id_a1", "p_id_0", "下周计划", "+ 8:00 起床\n+ 9:00 上班"),
    ("r_id_b0", "p_id_1", "下周计划", "+ 7:00 起床\n+ 8:00 上班"),
])


@pytest.fixture(scope="function")
def namespace_id() -> str:
    return "test"


@pytest.fixture(scope="function")
async def vector_db_init(client: httpx.Client, worker: Worker, namespace_id: str):
    for resource_id, parent_id, title, content in create_test_case[1]:
        await add_index(
            client, worker, title=title, content=content, namespace_id=namespace_id, space_type="private",
            resource_id=resource_id, parent_id=parent_id, user_id="test"
        )


@pytest.mark.parametrize("query, resource_ids, parent_ids", [
    ("下周计划", None, None),
    ("下周计划", ["r_id_a0", "r_id_b0"], None),
    ("下周计划", None, ["p_id_1"]),
    ("下周计划", ["r_id_b0"], ["p_id_0"])
])
def test_grimoire_stream(client: httpx.Client, vector_db_init: bool, namespace_id: str, query: str,
                         resource_ids: List[str] | None, parent_ids: List[str] | None):
    request = ChatRequest(session_id="fake_id", namespace_id=namespace_id, query=query,
                          resource_ids=resource_ids, parent_ids=parent_ids)
    assert_stream(api_stream(client, request))


@pytest.mark.parametrize("query, resource_ids, parent_ids", [
    ("下周计划", None, None),
])
def test_grimoire_stream(remote_client: httpx.Client, namespace_id: str, query: str,
                         resource_ids: List[str] | None, parent_ids: List[str] | None):
    request = ChatRequest(session_id="fake_id", namespace_id=namespace_id, query=query,
                          resource_ids=resource_ids, parent_ids=parent_ids)
    assert_stream(api_stream(remote_client, request))
