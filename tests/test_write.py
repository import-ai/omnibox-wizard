from typing import List

import httpx
import pytest

from tests.helper.fixture import client, worker
from tests.test_ask import assert_stream, api_stream, add_index, namespace_id
from wizard.grimoire.entity.api import AgentRequest
from wizard.wand.worker import Worker

create_test_case = ("resource_id, parent_id, title, content", [
    ("r_id_a0", "p_id_a", "周一计划", "+ 9:00 起床\n+ 10:00 上班"),
    ("r_id_a1", "p_id_a", "周二计划", "+ 8:00 起床\n+ 9:00 上班"),
    ("r_id_a2", "p_id_a", "周三计划", "+ 7:00 起床\n+ 8:00 上班"),
    ("r_id_a3", "p_id_a", "小红", "小红今年 8 岁"),
])


@pytest.fixture(scope="function")
async def vector_db_init(client: httpx.Client, worker: Worker, namespace_id: str):
    for resource_id, parent_id, title, content in create_test_case[1]:
        await add_index(
            client, worker, title=title, content=content, namespace_id=namespace_id,
            resource_id=resource_id, parent_id=parent_id, user_id="test"
        )


@pytest.mark.parametrize("enable_thinking", [True, False])
@pytest.mark.parametrize("query, resource_ids, parent_ids, expected_messages_length", [
    ("写一份计划书", None, ["p_id_a"], 5),
])
def test_write(client: httpx.Client, vector_db_init: bool, namespace_id: str, query: str, expected_messages_length: int,
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
    messages = assert_stream(api_stream(client, "/api/v1/wizard/write", request))
    assert len(messages) == expected_messages_length
