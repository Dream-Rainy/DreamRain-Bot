"""Internal adapter-neutral helpers for DreamRain plugins."""

from .capability import AdapterCapability, UnsupportedCapabilityError, get_capabilities
from .context import PlatformContext, get_group_id, get_user_id, is_group_event
from .message import Message, MessageSegment, at, coerce_message, image, prepend_at, text
from .sender import send_group, send_private, send_to_event

__all__ = [
    "AdapterCapability",
    "Message",
    "MessageSegment",
    "PlatformContext",
    "UnsupportedCapabilityError",
    "at",
    "coerce_message",
    "get_capabilities",
    "get_group_id",
    "get_user_id",
    "image",
    "is_group_event",
    "prepend_at",
    "send_group",
    "send_private",
    "send_to_event",
    "text",
]
