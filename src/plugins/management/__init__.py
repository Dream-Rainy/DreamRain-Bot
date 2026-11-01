"""Shared management plugin. Business modules register their own permission policy."""
import re

from nonebot import get_driver, get_plugin_config, logger, on_command
from nonebot.adapters import Bot, Event, Message
from nonebot.params import CommandArg
from nonebot.plugin import PluginMetadata

from src.plugins.platform_adapter import PlatformContext, send_to_event
from .config import Config
from .session import Sessions
from .portal import Portal, PATH, context_allowed
from .bridge import EditorBridge

__plugin_meta__ = PluginMetadata(name="管理后台", description="通用临时管理工作台", usage="私聊【管理后台 [公会战/别名] [群号]】", config=Config)
driver = get_driver()
config = get_plugin_config(Config)
portal = Portal(Sessions(superusers=lambda: driver.config.superusers))
bridge = None
command = on_command("管理后台", priority=5, block=True)


@command.handle()
async def open_management(bot: Bot, event: Event, args: Message = CommandArg()):
    global bridge
    context = PlatformContext.from_event(event, bot)
    arguments = args.extract_plain_text().split()
    module_id = {"公会战": "clanbattle", "别名": "aliases"}.get(arguments[0]) if arguments else None
    if module_id:
        arguments = arguments[1:]
    valid = len(arguments) <= 1 and (not arguments or re.fullmatch(r"[1-9][0-9]{0,19}", arguments[0]))
    group_id = int(arguments[0]) if valid and arguments else None
    message = ""
    if not context.is_private:
        message = "请私聊机器人发送【管理后台 [公会战/别名] [群号]】获取临时链接。"
    elif not config.management_web_enabled:
        message = "管理后台尚未启用。"
    elif not config.management_web_relay_url or not config.management_web_relay_token:
        message = "请配置 management_web_relay_url 和 management_web_relay_token。"
    elif not valid:
        message = "格式：【管理后台 [公会战/别名] [群号]】。"
    else:
        try:
            if bridge is None:
                bridge = EditorBridge(portal, config.management_web_relay_url, config.management_web_relay_token,
                                      api_path=PATH, base="/manage", page_path="/manage/")
            adapter = bot.adapter.get_name().split(maxsplit=1)[0].lower()
            label = getattr(getattr(event, "sender", None), "nickname", "") or event.get_user_id()
            identity = dict(platform_id=event.get_user_id(), adapter=adapter, label=str(label)[:128],
                            bot_id=str(bot.self_id), group_id=group_id)
            probe = portal.sessions.issue(**identity)
            try:
                if not context_allowed("management", probe):
                    raise ValueError("后台访问已被禁用")
                required = {module_id} if module_id else set()
                if group_id:
                    required.add("clanbattle")
                for name in required:
                    module = portal.modules.get(name)
                    if not module or not context_allowed(module.plugin, probe) or not await module.authorize(probe):
                        raise ValueError("没有该模块或指定群的访问权限")
            finally:
                portal.sessions.revoke(probe.key)
            entry = module_id or ("clanbattle" if group_id else None)
            url = await bridge.open(**identity, page_path=f"/manage/{entry}/" if entry else "/manage/")
            message = f"临时管理链接（最长一小时，请勿转发）：\n{url}"
        except Exception as exc:
            # Do not log transport exceptions: URLs may contain session credentials.
            logger.warning(f"Management session failed: {type(exc).__name__}")
            from fastapi import HTTPException
            message = str(exc.detail) if isinstance(exc, HTTPException) else str(exc) if isinstance(exc, ValueError) else "无法连接管理后台，请检查配置和网络。"
    await send_to_event(bot, event, message)
    await command.finish()


@driver.on_startup
async def ready():
    logger.info("Management modules: " + ", ".join(portal.modules))


@driver.on_shutdown
async def close():
    if bridge:
        await bridge.close()
    portal.sessions.clear()
