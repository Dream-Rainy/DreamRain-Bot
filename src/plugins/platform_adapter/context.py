from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def _call_string_method(obj: Any, name: str) -> str | None:
    method = getattr(obj, name, None)
    if not callable(method):
        return None
    try:
        value = method()
    except Exception:
        return None
    if value in (None, ""):
        return None
    return str(value)


def _first_attr(obj: Any, *names: str) -> Any:
    for name in names:
        value = getattr(obj, name, None)
        if value not in (None, ""):
            return value
    return None


def _first_nested_attr(obj: Any, *paths: tuple[str, ...]) -> Any:
    for path in paths:
        current = obj
        for name in path:
            current = getattr(current, name, None)
            if current is None:
                break
        if current not in (None, ""):
            return current
    return None


def _to_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def get_user_id(event: Any) -> int | None:
    return _to_int(_first_attr(event, "user_id", "sender_id", "from_id") or _call_string_method(event, "get_user_id"))


def get_group_id(event: Any) -> int | None:
    value = _first_attr(event, "group_id", "guild_id", "channel_id")
    if value is None:
        value = _first_nested_attr(event, ("chat", "id"), ("channel", "id"), ("guild", "id"))
    return _to_int(value)


def get_message_id(event: Any) -> str | None:
    value = _first_attr(event, "message_id", "id")
    if value is None:
        return None
    return str(value)


def get_plain_text(event: Any) -> str:
    text = _call_string_method(event, "get_plaintext")
    if text is not None:
        return text
    value = _first_attr(event, "raw_message", "message", "text")
    return "" if value is None else str(value)


def get_platform(bot: Any | None = None, event: Any | None = None) -> str:
    adapter = getattr(bot, "adapter", None)
    name = getattr(adapter, "get_name", None)
    if callable(name):
        try:
            return str(name()).lower()
        except Exception:
            pass
    event_name = event.__class__.__module__ if event is not None else ""
    if "onebot" in event_name:
        return "onebot"
    if "telegram" in event_name:
        return "telegram"
    return "unknown"


def is_group_event(event: Any) -> bool:
    return get_group_id(event) is not None


@dataclass(frozen=True)
class PlatformContext:
    platform: str
    user_id: int | None
    group_id: int | None
    message_id: str | None
    raw_message: str
    is_group: bool
    is_private: bool

    @classmethod
    def from_event(cls, event: Any, bot: Any | None = None) -> "PlatformContext":
        group_id = get_group_id(event)
        return cls(
            platform=get_platform(bot, event),
            user_id=get_user_id(event),
            group_id=group_id,
            message_id=get_message_id(event),
            raw_message=get_plain_text(event),
            is_group=group_id is not None,
            is_private=group_id is None,
        )

    def require_group_id(self) -> int:
        if self.group_id is None:
            raise ValueError("current event has no group context")
        return self.group_id
