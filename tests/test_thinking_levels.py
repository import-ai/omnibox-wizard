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
            },
            "default": {
                "default": {"edition": "basic", "level": level["id"]},
                "levels": [{"edition": "basic", "level": level["id"]}],
            },
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
    monkeypatch.setenv("OBW_MODELS", config([low]).model_dump_json())
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


def test_full_catalog_and_references(monkeypatch):
    raw = {
        "basic": {
            "default_level": "low",
            "levels": [
                {"id": "low", "model": "Instruct"},
                {"id": "high", "model": "Thinking"},
            ],
        },
        "pro": {
            "default_level": "high",
            "levels": [
                {
                    "id": level,
                    "model": "private",
                    "parameters": {"reasoning_effort": level},
                }
                for level in ("low", "high", "max")
            ],
        },
        "default": {
            "default_step": "pro.high",
            "steps": [
                "basic.low",
                "basic.high",
                "pro.low",
                "pro.high",
                "pro.max",
            ],
        },
    }
    models = ThinkingModels.model_validate(raw)
    public = models.public_config()
    assert {key: len(value["levels"]) for key, value in public.items()} == {
        "basic": 2,
        "pro": 3,
        "default": 5,
    }
    assert public["default"]["levels"] == [
        {"edition": step.split(".")[0], "level": step.split(".")[1]}
        for step in raw["default"]["steps"]
    ]
    assert public["default"]["default"] == {"edition": "pro", "level": "high"}
    assert "model" not in json.dumps(public)
    assert "parameters" not in json.dumps(public)
    basic_only = models.public_config(("basic",))
    assert set(basic_only) == {"basic", "default"}
    assert basic_only["default"]["default"] == {"edition": "basic", "level": "low"}
    monkeypatch.setenv("OBW_MODELS", models.model_dump_json())
    get_thinking_models.cache_clear()
    try:
        validate_selection("pro", "max", "pro")
        with pytest.raises(ValueError):
            validate_selection("pro", "max", "basic")
    finally:
        get_thinking_models.cache_clear()
    for steps, default in [
        (["pro.missing"], "pro.missing"),
        (["unknown.low"], "unknown.low"),
        (["basic.low", "basic.low"], "basic.low"),
        (["basic.low"], "pro.high"),
        (["low"], "low"),
    ]:
        with pytest.raises(ValidationError):
            ThinkingModels.model_validate(
                {**raw, "default": {"steps": steps, "default_step": default}}
            )


def test_private_prices_and_server_billing_snapshot(monkeypatch):
    from types import SimpleNamespace
    from wizard_common.grimoire.thinking import billing_headers

    raw = {
        "basic": {"default_level": "low", "levels": [{"id": "low", "model": "flash"}]},
        "pro": {"default_level": "max", "levels": [{"id": "max", "model": "pro"}]},
        "prices": {
            "flash": {"input": 80, "input_cached": 23, "output": 280},
            "pro": {"input": 800, "input_cached": 200, "output": 2800},
        },
    }
    monkeypatch.setenv("OBW_MODELS", json.dumps(raw))
    get_thinking_models.cache_clear()
    try:
        models = get_thinking_models()
        assert "prices" not in json.dumps(models.public_config())
        request = SimpleNamespace(edition=None, level=None)
        billing = json.loads(billing_headers(request, "pro")["X-Omnibox-Billing"])
        assert (request.edition, request.level) == ("pro", "max")
        assert billing == {"edition": "pro", "price": raw["prices"]["pro"]}
        basic = SimpleNamespace(edition="basic", level="low")
        assert (
            json.loads(billing_headers(basic, "basic")["X-Omnibox-Billing"])["edition"]
            == "basic"
        )
        with pytest.raises(ValueError):
            billing_headers(basic, "pro")
        for invalid in [-1, True, "800", 0.5]:
            with pytest.raises(ValidationError):
                ThinkingModels.model_validate(
                    {
                        **raw,
                        "prices": {"pro": {**raw["prices"]["pro"], "input": invalid}},
                    }
                )
    finally:
        get_thinking_models.cache_clear()
