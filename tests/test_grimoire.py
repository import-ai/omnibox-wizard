import json
from typing import Iterator

import httpx

from tests.helper.fixture import client
from wizard.grimoire.entity.api import ChatRequest


def assert_stream(stream: Iterator[str]):
    for each in stream:
        response = json.loads(each)
        if response["response_type"] == "delta":
            print(response["delta"], end="", flush=True)
        elif response["response_type"] == "citation_list":
            print("\n".join(["", "-" * 32, json.dumps(response["citation_list"], ensure_ascii=False)]))


def _stream(client: httpx.Client, request: ChatRequest) -> Iterator[str]:
    with client.stream("POST", "/api/v1/grimoire/stream", json=request.model_dump()) as response:
        if response.status_code != 200:
            raise Exception(f"{response.status_code} {response.text}")
        for line in response.iter_lines():
            if line.startswith("data: "):
                yield line[6:]


def test_grimoire_stream(client: httpx.Client):
    namespace_id = "test"
    query = "test"
    request = ChatRequest(session_id="fake_id", namespace_id=namespace_id, query=query)
    assert_stream(_stream(client, request))
