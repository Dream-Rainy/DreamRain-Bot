from __future__ import annotations

from typing import Any

from .capability import AdapterCapability, require_capability
from .message import coerce_message, prepend_at


async def send_to_event(bot: Any, event: Any, message: Any, *, at_sender: bool = False) -> Any:
    user_id = getattr(event, "user_id", None) if at_sender else None
    msg = prepend_at(message, user_id)
    return await bot.send(event=event, message=msg)


async def send_private(bot: Any, user_id: int | str, message: Any) -> Any:
    require_capability(bot, AdapterCapability.PRIVATE_SEND)
    return await bot.send_private_msg(user_id=int(user_id), message=coerce_message(message))


async def send_group(bot: Any, group_id: int | str, message: Any, **kwargs: Any) -> Any:
    require_capability(bot, AdapterCapability.GROUP_SEND)
    kwargs.pop("self_id", None)
    return await bot.send_group_msg(group_id=int(group_id), message=coerce_message(message), **kwargs)
