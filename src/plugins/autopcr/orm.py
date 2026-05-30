"""autopcr ORM bridge.

The upstream autopcr account/task data is file based; this module makes the
NoneBot ORM dependency explicit for the plugin and leaves room for future
adapter-owned tables.
"""

from nonebot import require

require("nonebot_plugin_orm")

from nonebot_plugin_orm import get_session  # noqa: E402

__all__ = ["get_session"]
