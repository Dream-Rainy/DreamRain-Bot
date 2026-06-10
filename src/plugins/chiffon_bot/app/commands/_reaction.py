"""Best-effort message reaction helpers for command acknowledgements."""

from __future__ import annotations

from typing import Any

from nonebot.log import logger

from src.plugins.platform_adapter.context import PlatformContext


DEFAULT_ACK_EMOJI_ID = 124


async def ack_message(event: Any, bot: Any, emoji_id: int = DEFAULT_ACK_EMOJI_ID) -> None:
    """Add a lightweight acknowledgement reaction to the triggering message.

    NapCat exposes this as an extended OneBot V11 API. The acknowledgement is a
    pure UX hint, so unsupported adapters or API failures must not interrupt the
    actual command flow.
    """
    ctx = PlatformContext.from_event(event, bot)
    if ctx.platform != "onebot" or ctx.message_id is None:
        return

    try:
        await bot.call_api(
            "set_msg_emoji_like",
            message_id=int(ctx.message_id),
            emoji_id=int(emoji_id),
            is_set=True,
        )
    except Exception as exc:
        logger.warning(f"发送消息确认表情失败: {exc}")
