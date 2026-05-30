from __future__ import annotations

from nonebot import get_plugin_config, require
from nonebot.plugin import PluginMetadata

from .config import Config

require("nonebot_plugin_localstore")
require("nonebot_plugin_orm")

__plugin_meta__ = PluginMetadata(
    name="autopcr",
    description="autopcr NoneBot adapter without the embedded HTTP server",
    usage="发送 #帮助 查看自动清日常指令",
    type="application",
    homepage="https://github.com/DreamRain/DreamRain-Bot",
    config=Config,
    supported_adapters={"~onebot.v11"},
    extra={"author": "DreamRain"},
)

plugin_config = get_plugin_config(Config)

from .storage import ensure_autopcr_storage  # noqa: E402

ensure_autopcr_storage()

from . import handlers as handlers  # noqa: E402,F401
