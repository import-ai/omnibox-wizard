from wizard_common.grimoire.agent.agent import Agent
from wizard_common.grimoire.entity.api import MessageDto


def test_prepare_model_messages_replaces_historical_current_time(monkeypatch):
    class FixedDatetime:
        @classmethod
        def now(cls):
            return cls()

        def astimezone(self):
            return self

        def isoformat(self):
            return "2026-09-09T22:30:00+08:00"

    monkeypatch.setattr(
        "wizard_common.grimoire.agent.agent.datetime", FixedDatetime
    )
    agent = object.__new__(Agent)
    messages = [
        MessageDto.model_validate(
            {
                "message": {
                    "role": "system",
                    "content": "# Meta info\n\n- Current time: 2026-08-09T10:00:00+08:00",
                }
            }
        ),
        MessageDto.model_validate(
            {"message": {"role": "user", "content": "What time is it?"}}
        ),
    ]

    model_messages = agent._prepare_model_messages(
        "Base system prompt", messages, "简体中文"
    )

    assert model_messages[0]["role"] == "system"
    assert "2026-09-09T22:30:00+08:00" in model_messages[0]["content"]
    assert "2026-08-09T10:00:00+08:00" not in str(model_messages)
    assert model_messages[1] == {"role": "user", "content": "What time is it?"}


def test_prepare_model_messages_refreshes_time_for_each_call(monkeypatch):
    current_times = iter(["first current time", "second current time"])
    monkeypatch.setattr(
        "wizard_common.grimoire.agent.agent.format_current_meta_info",
        lambda _lang: next(current_times),
    )
    agent = object.__new__(Agent)
    messages = [
        MessageDto.model_validate(
            {"message": {"role": "user", "content": "What time is it?"}}
        )
    ]

    first_messages = agent._prepare_model_messages("system", messages, "简体中文")
    second_messages = agent._prepare_model_messages("system", messages, "简体中文")

    assert first_messages[0]["content"] == "system\n\nfirst current time"
    assert second_messages[0]["content"] == "system\n\nsecond current time"
