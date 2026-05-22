"""priconne ORM - 依赖 nonebot-plugin-orm"""

from nonebot import require

require("nonebot_plugin_orm")

from nonebot_plugin_orm import get_session

from .models import WinRecord, SL, Subscribe, Tree, Apply, Record

__all__ = [
    "get_session",
    "WinRecord",
    "SL",
    "Subscribe",
    "Tree",
    "Apply",
    "Record",
]
