"""Register the private command for the independent alias editor."""
from __future__ import annotations

from fastapi import HTTPException
from nonebot import get_driver, logger
from nonebot.adapters import Bot, Event, Message
from nonebot.params import CommandArg

from src.plugins.platform_adapter import PlatformContext
from ...integrations.lxns.client import lxns_client
from ...shared.bot_response import BotResponse
from ..commands._response import finish_with
from .alias_portal import AliasPortal
from .session import EditorSessions


def register_alias_web(group, config):
    if not config.alias_web_enabled:
        return None
    driver = get_driver()
    sessions = EditorSessions(superusers=lambda: driver.config.superusers)
    portal = AliasPortal(lxns_client, sessions)
    _register_management(portal)
    if config.alias_web_relay_url:
        from .relay_bridge import EditorBridge
        portal.relay = EditorBridge(portal, config.alias_web_relay_url, config.alias_web_relay_token)
    editor = group.command("editor")

    @editor.handle()
    async def _arcade_editor(bot: Bot, event: Event, args: Message = CommandArg()):
        if not portal.relay:
            await finish_with(BotResponse(text="请先配置独立编辑器的 alias_web_relay_url 和 alias_web_relay_token。"))
            return
        context = PlatformContext.from_event(event, bot)
        if not context.is_private:
            await finish_with(BotResponse(text="请私聊机器人获取编辑链接，临时链接不能发在群里。"))
            return
        try:
            if args.extract_plain_text().strip():
                raise ValueError("直接发送 /arcade.editor 获取临时编辑链接，无需其他参数。")
            actor = await lxns_client.alias_actor(bot, event)
            adapter = bot.adapter.get_name().split(maxsplit=1)[0].lower()
            platform_id = event.get_user_id()
            sender = getattr(event, "sender", None)
            label = getattr(sender, "nickname", "") or f"{adapter} · {platform_id}"
            url = await portal.relay.open(user_id=actor, platform_id=platform_id, adapter=adapter, label=str(label)[:128])
            message = f"临时编辑链接（最长一小时）：\n{url}\n打开即可使用。链接相当于你的临时凭证，请勿转发。"
        except (ValueError, HTTPException) as exc:
            message = str(exc.detail) if isinstance(exc, HTTPException) else str(exc)
        except Exception as exc:
            logger.warning(f"Independent editor failed: {type(exc).__name__}")
            message = "无法连接独立编辑器，请检查中继服务、地址和服务密钥。"
        await finish_with(BotResponse(text=message))

    return portal


def _register_management(alias):
    from src.plugins.management import portal as management
    if "aliases" in management.modules:
        return
    from arcade_helper.web import BASE
    from src.plugins.management.portal import Module
    from .relay_bridge import API_PATH

    members = {}
    previous_portal = None

    def active_portal():
        from src.plugins.chiffon_bot import alias_portal
        return alias_portal

    async def authorize(member):
        return active_portal() is not None and member.adapter in {"onebot", "telegram", "discord", "kaiheila"}

    async def dispatch(member, method, path, query, body):
        nonlocal previous_portal
        alias = active_portal()
        if previous_portal is not alias:
            old, previous_portal = previous_portal, alias
            if old is not None:
                await old._close_internal_client()
        if not API_PATH.fullmatch(path):
            raise HTTPException(404, "别名接口不存在")
        linked = members.get(member.key)
        if linked is None or not alias.sessions.live(linked):
            platform = "qq" if member.adapter == "onebot" else member.adapter
            user = await alias.client.data.users.from_platform(platform, member.platform_id)
            linked = alias.sessions.issue(user_id=user.user_id, platform_id=member.platform_id,
                adapter=member.adapter, label=member.label,
                ttl=max(1, member.expires - management.sessions.clock()))
            members[member.key] = linked
            def cleanup():
                members.pop(member.key, None)
                alias.sessions.revoke(linked.key)
            member.cleanup.append(cleanup)
        if path == "logout":
            raise HTTPException(403, "请使用后台的退出按钮")
        response = await alias.internal_client().request(method, BASE + "/api/" + path, params=query,
            headers={"Authorization": f"Bearer {linked.key}"}, json=body if method == "POST" else None)
        if response.status_code >= 400:
            raise HTTPException(response.status_code, response.json().get("detail", "操作失败"))
        return response.json()

    management.register(Module("aliases", "别名审批", "chiffon_bot", dispatch, authorize))
