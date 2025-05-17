import json
from typing import Iterator, List

import httpx
import pytest

from tests.helper.fixture import client, worker
from wizard.entity import Task
from wizard.grimoire.entity.api import ChatRequest, AgentRequest, BaseChatRequest
from wizard.wand.worker import Worker


class Colors:
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    MAGENTA = '\033[95m'
    CYAN = '\033[96m'
    WHITE = '\033[97m'
    RESET = '\033[0m'


def print_colored(text, /, color, *args, **kwargs):
    print(f"{color}{text}{Colors.RESET}", *args, **kwargs)


def assert_stream(stream: Iterator[str]) -> list[dict]:
    messages = []
    for each in stream:
        response = json.loads(each)
        response_type = response["response_type"]
        assert response_type != "error"
        if response_type == "delta":
            print(response["delta"], end="", flush=True)
        elif response_type == "citations":
            print("\n".join(["", "-" * 32, json.dumps(response["citations"], ensure_ascii=False)]))
        elif response_type == "done":
            pass
        elif response_type == "openai_message":
            message = response["message"]
            messages.append(message)
        elif response_type == "think_delta":
            print_colored(response["delta"], color=Colors.MAGENTA, end="", flush=True)
        elif response_type == "tool_call":
            function_name: str = response["tool_call"]["function"]["name"]
            function_args: dict = response["tool_call"]["function"]["arguments"]
            str_function_args: str = json.dumps(function_args, separators=(',', ':'), ensure_ascii=False)
            print_colored(f"[Call {function_name} with arguments {str_function_args}]", color=Colors.YELLOW)
        else:
            raise RuntimeError(f"response_type: {response['response_type']}")
    return messages


def api_stream(client: httpx.Client, request: BaseChatRequest) -> Iterator[str]:
    url = "/api/v1/grimoire/stream"
    if isinstance(request, AgentRequest):
        url = "/api/v1/grimoire/ask"
    with client.stream("POST", url, json=request.model_dump()) as response:
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
        resource_id: str,
        parent_id: str,
        user_id: str
):
    task_body: dict = {
        "id": resource_id,  # Use resource id as fake task id
        "priority": 5,

        "function": "create_or_update_index",
        "input": {
            "title": title,
            "content": content,
            "meta_info": {
                "user_id": user_id,
                "resource_id": resource_id,
                "parent_id": parent_id,
            },
        },
        "namespace_id": namespace_id,
        "user_id": user_id
    }

    task: Task = Task.model_validate(task_body)
    processed_task = await worker.process_task(task, worker.get_trace_info(task))

    assert processed_task.created_at is not None
    assert processed_task.ended_at is not None

    output = processed_task.output
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
            client, worker, title=title, content=content, namespace_id=namespace_id,
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
def test_grimoire_stream_remote(remote_client: httpx.Client, namespace_id: str, query: str,
                                resource_ids: List[str] | None, parent_ids: List[str] | None):
    request = ChatRequest(session_id="fake_id", namespace_id=namespace_id, query=query,
                          resource_ids=resource_ids, parent_ids=parent_ids)
    assert_stream(api_stream(remote_client, request))


@pytest.mark.parametrize("query, resource_ids, parent_ids", [
    ("今天北京的天气", None, None),
    ("下周计划", None, None),
    ("下周计划", ["r_id_a0", "r_id_b0"], None),
    ("下周计划", None, ["p_id_1"]),
    ("下周计划", ["r_id_b0"], ["p_id_0"])
])
def test_agent(client: httpx.Client, vector_db_init: bool, namespace_id: str, query: str,
               resource_ids: List[str] | None, parent_ids: List[str] | None):
    request = AgentRequest.model_validate({
        "conversation_id": "fake_id",
        "query": query,
        "enable_thinking": True,
        "tools": [
            {
                "name": "knowledge_search",
                "namespace_id": namespace_id,
                "resource_ids": resource_ids,
                "parent_ids": parent_ids
            },
            {
                "name": "web_search"
            }
        ]
    })
    messages = assert_stream(api_stream(client, request))
    assert len(messages) == 5
