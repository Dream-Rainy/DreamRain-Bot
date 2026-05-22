from __future__ import annotations

from enum import StrEnum
from typing import Any


class AdapterCapability(StrEnum):
    EVENT_SEND = "event_send"
    GROUP_SEND = "group_send"
    PRIVATE_SEND = "private_send"
    IMAGE = "image"
    MENTION = "mention"
    GROUP_MEMBER_INFO = "group_member_info"


class UnsupportedCapabilityError(RuntimeError):
    def __init__(self, capability: AdapterCapability, platform: str = "unknown") -> None:
        super().__init__(f"{platform} adapter does not support {capability.value}")
        self.capability = capability
        self.platform = platform


def get_capabilities(bot: Any) -> set[AdapterCapability]:
    capabilities = {AdapterCapability.EVENT_SEND}
    if hasattr(bot, "send_group_msg"):
        capabilities.add(AdapterCapability.GROUP_SEND)
    if hasattr(bot, "send_private_msg"):
        capabilities.add(AdapterCapability.PRIVATE_SEND)
    if hasattr(bot, "get_group_member_info"):
        capabilities.add(AdapterCapability.GROUP_MEMBER_INFO)

    # Text is always representable; these two are common but still worth declaring.
    capabilities.add(AdapterCapability.IMAGE)
    capabilities.add(AdapterCapability.MENTION)
    return capabilities


def require_capability(bot: Any, capability: AdapterCapability) -> None:
    if capability not in get_capabilities(bot):
        adapter = getattr(bot, "adapter", None)
        name = getattr(adapter, "get_name", None)
        platform = str(name()).lower() if callable(name) else "unknown"
        raise UnsupportedCapabilityError(capability, platform)
