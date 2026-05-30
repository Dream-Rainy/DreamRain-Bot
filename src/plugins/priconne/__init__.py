from nonebot import require
from nonebot.plugin import PluginMetadata

require("nonebot_plugin_orm")
require("nonebot_plugin_localstore")

from .pcr_data_runtime import apply_pcr_data_override
from .config import Config

apply_pcr_data_override()

from . import login  # noqa: F401
from . import clanbattle  # noqa: F401
from . import fendao  # noqa: F401
from . import support_query  # noqa: F401
from . import games  # noqa: F401
from . import cherugo  # noqa: F401
from . import arena  # noqa: F401
from . import pcr_data_updater  # noqa: F401

__plugin_meta__ = PluginMetadata(
    name="priconne",
    description="公主连结 Re:Dive 相关功能：自动报刀、分刀、猜头像、猜角色、切噜语、arena 查作业等",
    usage="参见各子功能帮助",
    config=Config,
    type="application",
    supported_adapters={"~onebot.v11"},
)
