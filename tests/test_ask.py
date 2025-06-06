import json
from typing import Iterator, List

import httpx
import pytest

from tests.helper.fixture import client, worker
from wizard.entity import Task
from wizard.grimoire.entity.api import AgentRequest, BaseChatRequest
from wizard.grimoire.entity.tools import Condition
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


def print_colored(text, *, color, **kwargs):
    print(f"{color}{text}{Colors.RESET}", **kwargs)


def assert_stream(stream: Iterator[str]) -> list[dict]:
    messages = []
    for each in stream:
        response = json.loads(each)
        response_type = response["response_type"]
        assert response_type in ["bos", "delta", "eos", "done", "error"]
        assert response_type != "error"
        if response_type == "delta":
            message = response["message"]
            for key in ['content', 'reasoning_content']:
                if key in message:
                    messages[-1][key] = messages[-1].get(key, '') + message[key]
                    if key == 'reasoning_content':
                        print_colored(message[key], color=Colors.MAGENTA, end="", flush=True)
                    else:
                        print(message[key], end="", flush=True)
            for key in ['tool_calls', 'tool_call_id']:
                if key in message:
                    messages[-1][key] = message[key]
            if 'attrs' in response:
                messages[-1].setdefault('attrs', {}).update(response['attrs'])
        elif response_type == "bos":
            messages.append({'role': response['role']})
        elif response_type == "eos":
            print('\n\n' + '=' * 32 + '\n\n', end="", flush=True)
        elif response_type == "done":
            pass
        else:
            raise RuntimeError(f"response_type: {response['response_type']}")
    return messages


def api_stream(client: httpx.Client, url: str, request: BaseChatRequest) -> Iterator[str]:
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

        "function": "upsert_index",
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
    ("r_id_c0", "p_id_c", "小红", "小红今年 8 岁"),
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


@pytest.mark.parametrize("enable_thinking", [True, False])
@pytest.mark.parametrize("query, resource_ids, parent_ids, expected_messages_length", [
    # ("今天北京的天气", None, None, 5),
    # ("下周计划", None, None, 5),
    # ("我下周的计划", ["r_id_a0", "r_id_b0"], None, 5),
    # ("地球到火星的距离", ["r_id_a0", "r_id_b0"], None, 5),
    # ("下周计划", None, ["p_id_1"], 5),
    # ("下周计划", ["r_id_b0"], ["p_id_0"], 5),
    ("小红是谁？", ["r_id_a0", "r_id_a1", "r_id_b0", "r_id_c0"], None, 5),
])
def test_ask(client: httpx.Client, vector_db_init: bool, namespace_id: str, query: str, expected_messages_length: int,
             enable_thinking: bool, resource_ids: List[str] | None, parent_ids: List[str] | None):
    request = AgentRequest.model_validate({
        "conversation_id": "fake_id",
        "query": query,
        "enable_thinking": enable_thinking,
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
    messages = assert_stream(api_stream(client, "/api/v1/wizard/ask", request))
    assert len(messages) == expected_messages_length


@pytest.mark.parametrize("condition", [
    {"namespace_id": "asdf", "resource_ids": ["asdf"]},
    {"namespace_id": "asdf", "parent_ids": ["asdf"]},
    {"namespace_id": "asdf"},
    {"namespace_id": "asdf", "resource_ids": []},
    {"namespace_id": "asdf", "parent_ids": []},
])
def test_condition(condition: dict):
    condition = Condition.model_validate(condition)
    print(condition.to_chromadb_where())
