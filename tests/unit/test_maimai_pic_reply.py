from __future__ import annotations

from types import SimpleNamespace


async def test_select_image_message_uses_onebot_event_reply(loaded_chiffon_bot):
    from nonebot.adapters.onebot.v11 import Message, MessageSegment
    from nonebot_plugin_alconna.uniseg import Image, UniMessage

    from src.plugins.chiffon_bot.app.commands.maimai import _select_image_message

    event = SimpleNamespace(
        reply=SimpleNamespace(
            message=Message(MessageSegment.image("https://example.com/jacket.png"))
        )
    )

    result = await _select_image_message(
        event,
        UniMessage.text("/mai.pic"),
        adapter="OneBot V11",
    )

    assert result is not None
    assert Image in result
