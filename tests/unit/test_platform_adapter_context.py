from __future__ import annotations

from types import SimpleNamespace

from src.plugins.platform_adapter.context import PlatformContext, get_group_id, get_user_id


class DummyMessageEvent:
    user_id = "10001"
    group_id = "20002"
    message_id = 30003

    def get_plaintext(self) -> str:
        return "hello"


def test_context_reads_common_onebot_like_fields():
    ctx = PlatformContext.from_event(DummyMessageEvent())

    assert ctx.user_id == 10001
    assert ctx.group_id == 20002
    assert ctx.message_id == "30003"
    assert ctx.raw_message == "hello"
    assert ctx.is_group is True
    assert ctx.is_private is False


def test_context_reads_nested_chat_id_for_other_adapters():
    event = SimpleNamespace(
        chat=SimpleNamespace(id="9988"),
        user_id="7788",
        text="telegram text",
    )

    assert get_user_id(event) == 7788
    assert get_group_id(event) == 9988
    assert PlatformContext.from_event(event).raw_message == "telegram text"


def test_context_marks_private_when_group_is_missing():
    event = SimpleNamespace(user_id="1", raw_message="direct")
    ctx = PlatformContext.from_event(event)

    assert ctx.group_id is None
    assert ctx.is_group is False
    assert ctx.is_private is True
