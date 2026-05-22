from __future__ import annotations

import pytest

from src.plugins.platform_adapter.capability import AdapterCapability, UnsupportedCapabilityError
from src.plugins.platform_adapter.message import Message, MessageSegment, coerce_message, prepend_at
from src.plugins.platform_adapter.sender import send_group, send_private, send_to_event


class FakeEvent:
    user_id = 42


class FakeBot:
    def __init__(self) -> None:
        self.sent: list[tuple[str, object]] = []

    async def send(self, *, event, message):
        self.sent.append(("event", message))
        return "event-ok"

    async def send_group_msg(self, *, group_id, message):
        self.sent.append((f"group:{group_id}", message))
        return "group-ok"

    async def send_private_msg(self, *, user_id, message):
        self.sent.append((f"private:{user_id}", message))
        return "private-ok"


class EventOnlyBot:
    async def send(self, *, event, message):
        return None


def test_coerce_message_keeps_onebot_message_shape():
    msg = coerce_message("hello")

    assert isinstance(msg, Message)
    assert str(msg) == "hello"


def test_prepend_at_adds_mention_segment():
    msg = prepend_at("hello", 42)

    assert isinstance(msg[0], MessageSegment)
    assert msg[0].type == "at"
    assert str(msg).endswith("hello")


@pytest.mark.asyncio
async def test_send_to_event_can_at_sender():
    bot = FakeBot()

    result = await send_to_event(bot, FakeEvent(), "hello", at_sender=True)

    assert result == "event-ok"
    assert bot.sent[0][0] == "event"
    assert "hello" in str(bot.sent[0][1])


@pytest.mark.asyncio
async def test_targeted_sends_use_adapter_methods():
    bot = FakeBot()

    assert await send_group(bot, 123, "group", self_id=999) == "group-ok"
    assert await send_private(bot, 456, "private") == "private-ok"

    assert bot.sent[0] == ("group:123", Message("group"))
    assert bot.sent[1] == ("private:456", Message("private"))


@pytest.mark.asyncio
async def test_targeted_send_reports_missing_capability():
    with pytest.raises(UnsupportedCapabilityError) as exc_info:
        await send_group(EventOnlyBot(), 123, "group")

    assert exc_info.value.capability == AdapterCapability.GROUP_SEND
