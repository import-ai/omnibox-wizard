from wizard_common.grimoire.agent.agent import UserQueryPreprocessor
from wizard_common.grimoire.entity.api import MessageDto


def test_query_time_is_user_context_and_old_system_is_untouched():
    history = [
        MessageDto(message={"role": "system", "content": "Current time: 2025-01-01"}),
        MessageDto(
            message={"role": "user", "content": "今天几号？"},
            attrs={"user_context": {"created_at": "2026-09-12T10:30:00+08:00"}},
        ),
        MessageDto(message={"role": "assistant", "content": "hello"}),
    ]
    result = UserQueryPreprocessor.message_dtos_to_openai_messages(history)
    assert result[0] == history[0].message
    assert result[1]["role"] == "user"
    assert "<user_context_json>" in result[1]["content"]
    assert "2026-09-12T10:30:00+08:00" in result[1]["content"]
    assert history[1].message["content"] == "今天几号？"
    assert result == UserQueryPreprocessor.message_dtos_to_openai_messages(history)
    assert all("2026-09-12" not in m["content"] for m in result if m["role"] != "user")


def test_missing_time_and_permission_decisions_do_not_gain_a_timestamp():
    for attrs in [{}, {"tool_call": {"decisions": [{"type": "approve"}]}}]:
        message = MessageDto(message={"role": "user", "content": "hello"}, attrs=attrs)
        result = UserQueryPreprocessor.message_dtos_to_openai_messages([message])
        assert "created_at" not in str(result)
