import json
from unittest.mock import patch

import httpx
import pytest
from pydantic import ValidationError

from wizard_common.config import OpenAIConfig
from wizard_common.grimoire.thinking import (
    ThinkingModels,
    get_thinking_models,
    validate_selection,
)


def config(levels, default="low"):
    return ThinkingModels.model_validate(
        {"basic": {"default_level": default, "levels": levels}}
    )


@pytest.mark.asyncio
async def test_wire_payloads_and_public_config():
    samples = [
        ({"id": "low", "model": "Instruct"}, {"model": "Instruct"}),
        ({"id": "high", "model": "Thinking"}, {"model": "Thinking"}),
        (
            {"id": "low", "model": "toggle", "parameters": {"enable_thinking": False}},
            {"model": "toggle", "enable_thinking": False},
        ),
        (
            {"id": "high", "model": "toggle", "parameters": {"enable_thinking": True}},
            {"model": "toggle", "enable_thinking": True},
        ),
        (
            {
                "id": "ultra",
                "model": "effort",
                "parameters": {"reasoning_effort": "ultra"},
            },
            {"model": "effort", "reasoning_effort": "ultra"},
        ),
    ]
    connection = OpenAIConfig(
        api_key="private-key", base_url="https://model.invalid/v1", model="fallback"
    )
    for level, expected in samples:
        models = config([level], level["id"])
        public = models.public_config()
        assert public == {
            "basic": {
                "default": {"edition": "basic", "level": level["id"]},
                "levels": [{"edition": "basic", "level": level["id"]}],
            }
        }
        selected, kwargs = models.basic.select(level["id"]).resolve(connection)
        captured = []

        def handle(request):
            captured.append(json.loads(request.content))
            return httpx.Response(
                200,
                json={
                    "id": "test",
                    "object": "chat.completion",
                    "created": 0,
                    "model": expected["model"],
                    "choices": [],
                },
            )

        from openai import AsyncOpenAI

        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            sdk = AsyncOpenAI(
                api_key=selected.api_key, base_url=selected.base_url, http_client=client
            )
            with patch("wizard_common.config.AsyncOpenAI", return_value=sdk):
                await selected.chat(
                    messages=[{"role": "user", "content": "Hi"}], **kwargs
                )
        assert captured == [
            {"messages": [{"role": "user", "content": "Hi"}], **expected}
        ]
        assert connection.model == "fallback"


def test_validation(monkeypatch):
    low = {"id": "low", "model": "private-model"}
    for levels, default in [
        ([], "low"),
        ([low, low], "low"),
        ([low], "missing"),
        ([{**low, "parameters": {"model": "override"}}], "low"),
        ([{**low, "parameters": {"enable_thinking": "false"}}], "low"),
        (
            [
                {
                    **low,
                    "parameters": {"enable_thinking": False, "reasoning_effort": "low"},
                }
            ],
            "low",
        ),
    ]:
        with pytest.raises(ValidationError):
            config(levels, default)
    monkeypatch.setenv("OBW_THINKING_MODELS", config([low]).model_dump_json())
    get_thinking_models.cache_clear()
    try:
        validate_selection("basic", "low")
        validate_selection(None, None)
        for selection in [
            ("pro", "low"),
            ("basic", "missing"),
            (None, "low"),
            ("basic", None),
            ("default", "basic.low"),
        ]:
            with pytest.raises(ValueError):
                validate_selection(*selection)
    finally:
        get_thinking_models.cache_clear()
