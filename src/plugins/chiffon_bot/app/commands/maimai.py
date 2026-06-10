"""maimai 命令注册 — 通用命令由工厂生成，此文件仅保留 maimai 特有命令。"""

from __future__ import annotations

from typing import NoReturn

from nonebot import on_fullmatch
from nonebot.adapters import Bot, Event, Message
from nonebot.exception import MatcherException
from nonebot.internal.matcher import Matcher
from nonebot.log import logger
from nonebot.params import CommandArg

from ...domains.maimai.handlers.b50 import b50
from ...domains.maimai.handlers.profile import profile
from ...domains.maimai.handlers.r50 import r50
from ...domains.maimai.handlers.trend import generate_trend_plot
from ...domains.maimai.handlers.network import get_page_screenshot
from ...domains.maimai.maimai_adapter import get_maimai_adapter
from ...integrations.lxns.binding import ensure_user_bound
from ...integrations.lxns.use_cases.bind import bind_by_friend_code
from ...integrations.lxns.use_cases.default_account import (
    get_default_lxns_game_profile_by_qq,
)
from ...integrations.lxns.use_cases.unbind import unbind_lxns_for_qq
from ...integrations.lxns.plugin_data import plugin_data
from ...integrations.lxns.session import UserSession
from ...infra.db.models import User
from ...shared.bot_response import BotResponse

from ._reaction import ack_message
from ._response import finish_with
from .game_command_factory import register_game_commands

import traceback


def register_maimai_commands(maimai_group):
    # 通用命令（help / song / alias / random / update / clean + 自然语言）
    register_game_commands(maimai_group, get_maimai_adapter())

    async def get_userinfo(matcher: type[Matcher], user_id: str) -> User | NoReturn:
        try:
            user = await UserSession.from_user_qq(dev_headers=plugin_data.headers, qq=user_id)
            return user.user
        except Exception as e:
            traceback.print_exc()
            logger.error(f"获取用户信息失败: {user_id}")
            logger.error(f"错误信息: {e}")
            await matcher.finish(
                "哎呀，没有找到对应的玩家哦~\n"
                + "或许，也可以通过 /mai.bind 命令进行绑定，解锁更多功能呢"
            )

    # ── bind ───────────────────────────────────────────────────────────
    bind_command = maimai_group.command("bind", force_whitespace=True)

    @bind_command.handle()
    async def handle_bind(event: Event, args: Message = CommandArg()):
        user_id = event.get_user_id()
        friend_code = args.extract_plain_text().strip()
        if not friend_code:
            await bind_command.finish(
                "用法：/mai.bind <friend_code>\n"
                + "（推荐新入口：/acc bind <friend_code>）"
            )

        try:
            result = await bind_by_friend_code(qq=user_id, friend_code=friend_code)
        except MatcherException:
            raise

        await finish_with(BotResponse(
            text=result.message
            + "\n\n（提示：账号相关指令已迁移到 /acc，例如：/acc bind、/acc unbind、/acc default、/acc list）",
            reply_to=event.message_id,
        ))

    # ── unbind ─────────────────────────────────────────────────────────
    unbind_command = maimai_group.command("unbind", force_whitespace=True)

    @unbind_command.handle()
    async def handle_unbind(event: Event):
        user_id = event.get_user_id()
        result = await unbind_lxns_for_qq(qq=user_id)
        await unbind_command.finish(
            result.message
            + "\n\n（提示：账号相关指令已迁移到 /acc，例如：/acc bind、/acc unbind、/acc default、/acc list）"
        )

    # ── b50 ────────────────────────────────────────────────────────────
    b50_command = maimai_group.command("b50", force_whitespace=True)

    @b50_command.handle()
    async def handle_b50(bot: Bot, event: Event):
        user_id = event.get_user_id()
        await ack_message(event, bot)

        bind_result = await ensure_user_bound(user_id, plugin_data.headers)
        if bind_result.status not in ["bound", "already_bound"]:
            await b50_command.finish(f"自动绑定失败：{bind_result.message}")

        gp = await get_default_lxns_game_profile_by_qq(user_id)
        friend_code = gp.maimai_friend_code if gp else None
        if not friend_code:
            await b50_command.finish("未绑定或未设置 maimai 好友码，请先绑定后再试")
        response = await b50(str(friend_code), plugin_data.headers, user_id, event.message_id)
        await finish_with(response)

    # ── r50 ────────────────────────────────────────────────────────────
    r50_command = maimai_group.command("r50", force_whitespace=True)

    @r50_command.handle()
    async def handle_r50(bot: Bot, event: Event):
        user_id = event.get_user_id()
        await ack_message(event, bot)

        bind_result = await ensure_user_bound(user_id, plugin_data.headers)
        if bind_result.status not in ["bound", "already_bound"]:
            await r50_command.finish(f"自动绑定失败：{bind_result.message}")

        gp = await get_default_lxns_game_profile_by_qq(user_id)
        friend_code = gp.maimai_friend_code if gp else None
        if not friend_code:
            await r50_command.finish("未绑定或未设置 maimai 好友码，请先绑定后再试")
        response = await r50(str(friend_code), plugin_data.headers, user_id, event.message_id)
        await finish_with(response)

    # ── profile ────────────────────────────────────────────────────────
    profile_command = maimai_group.command("profile", force_whitespace=True)

    @profile_command.handle()
    async def handle_profile(bot: Bot, event: Event):
        user_id = event.get_user_id()
        await ack_message(event, bot)

        bind_result = await ensure_user_bound(user_id, plugin_data.headers)
        if bind_result.status not in ["bound", "already_bound"]:
            await profile_command.finish(f"自动绑定失败：{bind_result.message}")

        gp = await get_default_lxns_game_profile_by_qq(user_id)
        friend_code = gp.maimai_friend_code if gp else None
        if not friend_code:
            await profile_command.finish("未绑定或未设置 maimai 好友码，请先绑定后再试")
        response = await profile(str(friend_code), plugin_data.headers, user_id, event.message_id)
        await finish_with(response)

    # ── trend ──────────────────────────────────────────────────────────
    trend_command = maimai_group.command("trend", force_whitespace=True)

    @trend_command.handle()
    async def handle_trend(bot: Bot, event: Event):
        user_id = event.get_user_id()
        await ack_message(event, bot)

        bind_result = await ensure_user_bound(user_id, plugin_data.headers)
        if bind_result.status not in ["bound", "already_bound"]:
            await trend_command.finish(f"自动绑定失败：{bind_result.message}")

        gp = await get_default_lxns_game_profile_by_qq(user_id)
        friend_code = gp.maimai_friend_code if gp else None
        if not friend_code:
            await trend_command.finish("未绑定或未设置 maimai 好友码，请先绑定后再试")
        response = await generate_trend_plot(str(friend_code), plugin_data.headers)
        await finish_with(response)

    # ── network ────────────────────────────────────────────────────────
    network_command = on_fullmatch(("断网", "网炸了？", "网炸了?", "网怎么样"), ignorecase=False)

    @network_command.handle()
    async def handle_network_check(bot: Bot, event: Event):
        await ack_message(event, bot)
        screenshot_bytes = await get_page_screenshot()
        await finish_with(BotResponse(image=screenshot_bytes))
