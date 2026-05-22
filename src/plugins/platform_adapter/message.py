from __future__ import annotations

import base64
import io
from typing import Any

from PIL import Image
from nonebot.adapters.onebot.v11 import Message, MessageSegment


def text(content: Any) -> MessageSegment:
    return MessageSegment.text(str(content))


def image(data: str | bytes) -> MessageSegment:
    return MessageSegment.image(data)


def at(user_id: int | str) -> MessageSegment:
    return MessageSegment.at(user_id)


def coerce_message(message: Any) -> Message:
    if isinstance(message, Message):
        return message
    if isinstance(message, MessageSegment):
        return Message(message)
    if isinstance(message, bytes):
        return Message(image(message))
    if isinstance(message, Image.Image):
        buffer = io.BytesIO()
        message.save(buffer, format="PNG")
        data = "base64://" + base64.b64encode(buffer.getvalue()).decode()
        return Message(image(data))
    if message is None:
        return Message()
    return Message(str(message))


def prepend_at(message: Any, user_id: int | str | None) -> Message:
    msg = coerce_message(message)
    if user_id is None:
        return msg
    return Message(at(user_id)) + Message(" ") + msg
