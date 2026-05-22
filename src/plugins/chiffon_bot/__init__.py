from nonebot import get_plugin_config, get_driver, CommandGroup, logger
from nonebot.plugin import PluginMetadata

from .config import Config
from .integrations.lxns.plugin_data import plugin_data

# 确保 DomainAdapter 在命令注册前完成注册
from .domains.maimai import maimai_adapter as _  # noqa: F401
from .domains.chunithm import chunithm_adapter as _  # noqa: F401

from .app.commands.account import register_account_commands
from .app.commands.maimai import register_maimai_commands
from .app.commands.chunithm import register_chunithm_commands
from .app.commands.event import register_event_commands, register_event_rank_matcher
from .app.commands.natural_language import register_natural_language_commands
from .app.http.oauth_callback import register_oauth_callback_route

from .infra.db.connect import init as init_db, close as close_db
from .domains.maimai.services import refresh_song_data

__plugin_meta__ = PluginMetadata(
    name="src/plugins/chiffon_bot",
    description="",
    usage="",
    config=Config,
)

plugin_config = get_plugin_config(Config)

plugin_data.headers = {
    'Authorization': plugin_config.lxns_api_key,
}

maimai_group = CommandGroup("mai", prefix_aliases=True, priority=5)
register_maimai_commands(maimai_group)

chuni_group = CommandGroup("chuni", prefix_aliases=True, priority=5)
register_chunithm_commands(chuni_group)

account_group = CommandGroup("acc", prefix_aliases=True, priority=5)
register_account_commands(account_group)

event_group = CommandGroup("event", prefix_aliases=True, priority=5)
register_event_commands(event_group)
register_event_rank_matcher()

register_natural_language_commands()
register_oauth_callback_route()

driver = get_driver()


@driver.on_startup
async def init():
    await init_db()
    logger.info("开始初始化乐曲数据...")
    is_updated, msg = await refresh_song_data()
    if is_updated:
        logger.info(f"乐曲数据初始化完成: {msg}")
    else:
        logger.warning(f"乐曲数据初始化未加载到本地数据: {msg}")


@driver.on_shutdown
async def close():
    await close_db()
