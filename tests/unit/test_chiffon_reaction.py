from __future__ import annotations

from types import SimpleNamespace


class FakeAdapter:
    def __init__(self, name: str) -> None:
        self._name = name

    def get_name(self) -> str:
        return self._name


class FakeBot:
    def __init__(self, adapter_name: str) -> None:
        self.adapter = FakeAdapter(adapter_name)
        self.calls: list[tuple[str, dict]] = []

    async def call_api(self, api: str, **kwargs):
        self.calls.append((api, kwargs))


async def test_ack_message_calls_napcat_emoji_like_for_onebot_v11():
    from src.plugins.chiffon_bot.app.commands._reaction import ack_message

    bot = FakeBot("OneBot V11")
    event = SimpleNamespace(message_id=12345, group_id=10000)

    await ack_message(event, bot, emoji_id=124)

    assert bot.calls == [
        (
            "set_msg_emoji_like",
            {
                "message_id": 12345,
                "emoji_id": "124",
                "set": True,
            },
        )
    ]


async def test_ack_message_skips_non_onebot_platform():
    from src.plugins.chiffon_bot.app.commands._reaction import ack_message

    bot = FakeBot("Telegram")
    event = SimpleNamespace(message_id=12345)

    await ack_message(event, bot)

    assert bot.calls == []
