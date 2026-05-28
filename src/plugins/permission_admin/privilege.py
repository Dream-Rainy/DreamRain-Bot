from __future__ import annotations

from enum import IntEnum
from typing import TYPE_CHECKING, Any

from nonebot.internal.adapter import Event

from src.plugins.platform_adapter.context import get_group_id, get_user_id

if TYPE_CHECKING:
    from .core import PermissionManager


class PrivilegeLevel(IntEnum):
    BLACK = -999
    DEFAULT = 0
    NORMAL = 1
    PRIVATE = 10
    ADMIN = 21
    OWNER = 22
    WHITE = 51
    SUPERUSER = 999

    @classmethod
    def from_string(cls, value: str) -> "PrivilegeLevel | None":
        upper = value.upper()
        try:
            return cls[upper]
        except KeyError:
            try:
                return cls(int(value))
            except (ValueError, KeyError):
                return None


_LEVEL_NAMES: dict[int, str] = {
    -999: "BLACK",
    0: "DEFAULT",
    1: "NORMAL",
    10: "PRIVATE",
    21: "ADMIN",
    22: "OWNER",
    51: "WHITE",
    999: "SUPERUSER",
}


def level_name(level: int) -> str:
    return _LEVEL_NAMES.get(level, str(level))


_POWER_LEVEL_BY_NAME: dict[str, int] = {
    "owner": PrivilegeLevel.OWNER,
    "admin": PrivilegeLevel.ADMIN,
    "member": PrivilegeLevel.NORMAL,
}


def resolve_user_level(event: Event, mgr: "PermissionManager", bot: Any = None) -> PrivilegeLevel:
    """解析用户在当前事件上下文中的特权等级。"""
    uid = get_user_id(event)

    # 1. 全局黑名单
    if uid is not None and uid in mgr._global_blacklist:
        return PrivilegeLevel.BLACK

    # 2. SUPERUSER
    if uid is not None and bot is not None:
        try:
            adapter_name = bot.adapter.get_name().split(maxsplit=1)[0].lower()
            superusers = bot.config.superusers
            if f"{adapter_name}:{uid}" in superusers or str(uid) in superusers:
                return PrivilegeLevel.SUPERUSER
        except Exception:
            pass

    # 3. 全局白名单
    if uid is not None and uid in mgr._global_whitelist:
        return PrivilegeLevel.WHITE

    # 4. 群角色
    gid = get_group_id(event)
    if gid is not None:
        sender = getattr(event, "sender", None)
        if sender is not None:
            role = getattr(sender, "role", None)
            if role is not None:
                role_name = str(role).lower()
                level = _POWER_LEVEL_BY_NAME.get(role_name)
                if level is not None:
                    return PrivilegeLevel(level)
        return PrivilegeLevel.NORMAL

    # 5. 私聊
    return PrivilegeLevel.PRIVATE
