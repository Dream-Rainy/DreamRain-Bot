"""平台无关的 Bot 响应类型。

Handler 返回此类型替代 adapter 专属的 Message 对象，
命令层通过 SAA 将其转换为当前 adapter 的消息。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class BotResponse:
    """跨平台的机器人响应。

    至少需设置一个字段。常见组合：

    - 纯文本：``BotResponse(text="...")``
    - 文本 + 回复：``BotResponse(text="...", reply_to=msg_id)``
    - 图片 + 回复：``BotResponse(image=bytes, reply_to=msg_id)``
    - 图片 + 文本 + 回复：``BotResponse(image=bytes, text="...", reply_to=msg_id)``
    - 图片 + 回复 + 附加提示：``BotResponse(image=bytes, reply_to=msg_id, suffix="timing")``
    """

    text: str | None = None
    image: bytes | None = None
    reply_to: int | None = None
    suffix: str | None = None

    def __bool__(self) -> bool:
        return bool(self.text or self.image or self.suffix)
