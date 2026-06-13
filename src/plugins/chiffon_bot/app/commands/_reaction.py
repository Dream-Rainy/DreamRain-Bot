"""Best-effort message reaction helpers for command acknowledgements.

Currently this helper targets NapCat's OneBot V11 extension only. Lagrange and
LLOneBot expose similar reactions with different APIs and are intentionally not
handled here yet.
"""

from __future__ import annotations

from typing import Any

from nonebot.log import logger

from src.plugins.platform_adapter.context import PlatformContext


DEFAULT_ACK_EMOJI_ID = "124"


async def ack_message(event: Any, bot: Any, emoji_id: str | int = DEFAULT_ACK_EMOJI_ID) -> None:
    """Add a lightweight acknowledgement reaction to the triggering message.

    NapCat exposes this as an extended OneBot V11 API. The acknowledgement is a
    pure UX hint, so unsupported adapters or API failures must not interrupt the
    actual command flow.
    """
    ctx = PlatformContext.from_event(event, bot)
    if "onebot" not in ctx.platform or ctx.message_id is None or ctx.is_private:
        logger.info("当前平台或消息不支持消息确认表情，跳过")
        return

    try:
        await bot.call_api(
            "set_msg_emoji_like",
            message_id=int(ctx.message_id),
            emoji_id=str(emoji_id),
            set=True,
        )
    except Exception as exc:
        logger.warning(f"发送消息确认表情失败: {exc}")
