import json as jsonlib
from typing import Iterator, List

import httpx
import pytest

from omnibox_wizard.wizard.entity import Task
from omnibox_wizard.wizard.grimoire.agent.agent import UserQueryPreprocessor
from omnibox_wizard.wizard.grimoire.entity.api import MessageDto
from omnibox_wizard.wizard.grimoire.entity.tools import Condition
from omnibox_wizard.wizard.wand.worker import Worker
from tests.omnibox_wizard.helper.fixture import client, worker


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
        response = jsonlib.loads(each)
        response_type = response["response_type"]
        assert response_type in ["bos", "delta", "eos", "done", "error"]
        assert response_type != "error"
        if response_type == "delta":
            message = response["message"]
            for key in ['content', 'reasoning_content']:
                if key in message:
                    messages[-1][key] = messages[-1].get(key, '') + message[key]
            for key in ['tool_calls', 'tool_call_id']:
                if key in message:
                    messages[-1][key] = message[key]
            if 'attrs' in response:
                messages[-1].setdefault('attrs', {}).update(response['attrs'])
        elif response_type == "bos":
            messages.append({'role': response['role']})
        elif response_type == "eos":
            message_dto = MessageDto.model_validate({"message": messages[-1], "attrs": messages[-1].get('attrs', None)})
            for key in ['reasoning_content', 'content']:
                if content := message_dto.message.get(key, ""):
                    if key == 'reasoning_content':
                        print_colored(content, color=Colors.MAGENTA, end="", flush=True)
                    else:
                        if message_dto.message['role'] == 'user':
                            content = UserQueryPreprocessor.parse_message(message_dto)["content"]
                        print(content, end="", flush=True)
            if tool_calls := message_dto.message.get('tool_calls', []):
                print_colored(jsonlib.dumps(tool_calls, ensure_ascii=False), color=Colors.YELLOW, end="", flush=True)

            print('\n\n' + '=' * 32 + '\n\n', end="", flush=True)
        elif response_type == "done":
            pass
        else:
            raise RuntimeError(f"response_type: {response['response_type']}")
    return messages


def api_stream(client: httpx.Client, url: str, request: dict) -> Iterator[str]:
    with client.stream("POST", url, json=request) as response:
        if response.status_code != 200:
            raise Exception(f"{response.status_code} {response.read().decode('utf-8')}")
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
    assert processed_task.exception is None, f"Task failed with exception: {processed_task.exception}"

    output = processed_task.output
    assert output["success"] is True


dir_name: dict[str, str] = {
    "p_id_a": "下周计划",
    "p_id_b": "人物",
}

create_test_case = ("resource_id, parent_id, title, content", [
    ("r_id_a0", "p_id_a", "周一计划", "+ 9:00 起床\n+ 10:00 上班"),
    ("r_id_a1", "p_id_a", "周二计划", "+ 8:00 起床\n+ 9:00 上班"),
    ("r_id_b0", "p_id_a", "周三计划", "+ 7:00 起床\n+ 8:00 上班"),
    ("r_id_c0", "p_id_b", "小红", "小红今年 8 岁"),
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


def get_resource(resource_id: str) -> dict:
    for rid, pid, title, content in create_test_case[1]:
        if resource_id == rid:
            return {
                "name": title,
                "id": rid,
                "type": "resource",
            }


def get_folder(parent_id: str) -> dict:
    return {
        "name": dir_name[parent_id],
        "id": parent_id,
        "type": "folder",
        "child_ids": [rid for rid, pid, _, _ in create_test_case[1] if pid == parent_id]
    }


def get_resource_ids(parent_id: str) -> List[str]:
    return [rid for rid, pid, _, _ in create_test_case[1] if pid == parent_id]


def get_agent_request(
        namespace_id: str,
        query: str,
        resource_ids: List[str] | None = None,
        parent_ids: List[str] | None = None,
        enable_thinking: bool = False
) -> dict:
    return {
        "conversation_id": "fake_id",
        "query": query,
        "enable_thinking": enable_thinking,
        "tools": [
            {
                "name": "private_search",
                "namespace_id": namespace_id,
                "visible_resources": [
                    *map(get_resource, resource_ids or []),
                    *map(get_resource, sum(map(get_resource_ids, parent_ids or []), []))
                ],
                "resources": [
                    *map(get_resource, resource_ids or []),
                    *map(get_folder, parent_ids or []),
                ]
            },
            {
                "name": "web_search"
            }
        ]
    }


@pytest.mark.parametrize("enable_thinking", [True, False, None])
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
    request = get_agent_request(
        namespace_id=namespace_id,
        query=query,
        resource_ids=resource_ids,
        parent_ids=parent_ids,
        enable_thinking=enable_thinking
    )
    messages = assert_stream(api_stream(client, "/api/v1/wizard/ask", request))
    cnt: int = len(messages)
    assert cnt == expected_messages_length


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
