"""SAA 消息转换工具。

将 BotResponse 转换为 SAA MessageFactory 并发送/结束。
"""

from __future__ import annotations

from typing import NoReturn

from nonebot_plugin_saa import MessageFactory, Text, Image as SaaImage, Reply

from ...shared.bot_response import BotResponse


def _build(response: BotResponse) -> list:
    segs: list = []
    if response.reply_to is not None:
        segs.append(Reply(response.reply_to))
    if response.text is not None:
        segs.append(Text(response.text))
    if response.image is not None:
        segs.append(SaaImage(raw=response.image))
    if response.suffix is not None:
        segs.append(Text(response.suffix))
    return segs


async def finish_with(response: BotResponse) -> NoReturn:
    """用 SAA 发送 BotResponse 并结束当前 matcher。"""
    await MessageFactory(_build(response)).finish()


async def send_with(response: BotResponse) -> None:
    """用 SAA 发送 BotResponse 但不结束 matcher（用于先发图片再发文本等场景）。"""
    await MessageFactory(_build(response)).send()
