from typing import List

import httpx
import pytest

from tests.helper.fixture import client
from tests.test_ask import assert_stream, api_stream, namespace_id, get_agent_request, vector_db_init


@pytest.mark.parametrize("enable_thinking", [True, False])
@pytest.mark.parametrize("query, resource_ids, parent_ids, expected_messages_length", [
    ("根据这些材料写一份计划书", None, ["p_id_a"], 5),
])
def test_write(client: httpx.Client, vector_db_init: bool, namespace_id: str, query: str, expected_messages_length: int,
               enable_thinking: bool, resource_ids: List[str] | None, parent_ids: List[str] | None):
    request = get_agent_request(
        namespace_id=namespace_id,
        query=query,
        resource_ids=resource_ids,
        parent_ids=parent_ids,
        enable_thinking=enable_thinking
    )
    messages = assert_stream(api_stream(client, "/api/v1/wizard/write", request))
    assert len(messages) == expected_messages_length
