import httpx

from tests.helper.fixture import base_url, namespace_id


async def test_api(base_url: str, namespace_id: str):
    async with httpx.AsyncClient(base_url=base_url) as client:
        response: httpx.Response = await client.post("/task", json={
            "function": "html_to_markdown",
            "input": "<p>hello world</p>",
            "namespace_id": namespace_id
        })
        response.raise_for_status()
        json_response: dict = response.json()
        task_id: str = json_response["task_id"]
        assert len(task_id) == 22
