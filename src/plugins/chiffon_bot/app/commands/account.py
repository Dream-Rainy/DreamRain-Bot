from __future__ import annotations

import asyncio

from nonebot.adapters import Event, Message
from nonebot.log import logger
from nonebot.params import CommandArg

from ...integrations.lxns.use_cases.bind import bind_by_friend_code
from ...integrations.lxns.oauth_client import oa_client
from ...integrations.lxns.sse_client import sse_client
from ...integrations.lxns.use_cases.bind_oauth import bind_by_oauth_code
from ...integrations.lxns.use_cases.default_account import (
    get_default_lxns_game_profile_by_qq,
    set_default_lxns_account_for_qq,
)
from ...integrations.lxns.use_cases.unbind import unbind_lxns_for_qq
from ...infra.db.models import GameProfile, QQ_PLATFORM, UserAccount
from ...shared.bot_response import BotResponse
from ._response import finish_with, send_with


def register_account_commands(acc_group):
    help_command = acc_group.command("help", force_whitespace=True)

    @help_command.handle()
    async def handle_help(event: Event):
        await help_command.finish(
            "[account] 帮助\n"
            + "绑定（friend_code）：/acc.bind <friend_code>\n"
            + "OAuth 绑定：/acc.bind\n"
            + "OAuth 绑定状态：/acc.oauth-status\n"
            + "解绑 LXNS：/acc.unbind\n"
            + "查看默认账号：/acc.default show\n"
            + "设置默认账号：/acc.default set <lxns_account_key>\n"
            + "列出已绑定账号：/acc.list\n"
        )

    bind_command = acc_group.command("bind", force_whitespace=True)

    @bind_command.handle()
    async def handle_bind(event: Event, args: Message = CommandArg()):
        user_id = event.get_user_id()
        friend_code = args.extract_plain_text().strip()

        # 有 friend_code → 传统绑定
        if friend_code:
            result = await bind_by_friend_code(qq=user_id, friend_code=friend_code)
            await finish_with(BotResponse(text=result.message, reply_to=event.message_id))

        # 无参数 → OAuth 流程
        if not oa_client.redirect_uri:
            await bind_command.finish(
                "OAuth 未配置 redirect_uri 或 relay_url，暂不可用"
            )

        state = oa_client.add_wait_bind_user(user_id)
        bind_uri = oa_client.get_bind_uri(state)
        await send_with(BotResponse(
            text=f"已生成 OAuth 授权链接，请在浏览器中打开完成授权：\n{bind_uri}",
            reply_to=event.message_id,
        ))

        future = sse_client.register(state)
        try:
            code = await asyncio.wait_for(future, timeout=oa_client.state_ttl_seconds)
        except asyncio.TimeoutError:
            await finish_with(BotResponse(text="OAuth 绑定超时，请重试", reply_to=event.message_id))
        finally:
            sse_client.unregister(state)

        result = await bind_by_oauth_code(qq=user_id, code=code, state=state)

        if result.status == "bound":
            account_key = result.account_key
            await finish_with(BotResponse(
                text=f"OAuth 绑定成功！你现在可以使用相关功能。\naccount_key: {account_key}",
                reply_to=event.message_id,
            ))
        else:
            await finish_with(BotResponse(
                text=f"OAuth 绑定失败：{result.message}",
                reply_to=event.message_id,
            ))

    oauth_status_command = acc_group.command("oauth-status", force_whitespace=True)

    @oauth_status_command.handle()
    async def handle_oauth_status(event: Event):
        user_id = event.get_user_id()
        oa_client.cleanup_wait_bind_user()

        result = oa_client.get_bind_result_by_user(user_id)
        if result is not None:
            account_key = result.get("account_key") or ""
            await finish_with(BotResponse(
                text=f"最近一次 OAuth 状态：{result.get('status')}\n"
                + f"说明：{result.get('message')}\n"
                + (f"account_key: {account_key}" if account_key else ""),
                reply_to=event.message_id,
            ))

        pending_state = next(
            (state for state, data in oa_client.wait_bind_user.items() if data.get("user_id_hash") == user_id),
            None,
        )
        if pending_state is not None:
            await finish_with(BotResponse(
                text="当前 OAuth 授权仍在等待回调完成，请稍后重试。",
                reply_to=event.message_id,
            ))

        await finish_with(BotResponse(text="暂无 OAuth 绑定记录", reply_to=event.message_id))

    unbind_command = acc_group.command("unbind", force_whitespace=True)

    @unbind_command.handle()
    async def handle_unbind(event: Event):
        user_id = event.get_user_id()
        result = await unbind_lxns_for_qq(qq=user_id)
        await unbind_command.finish(result.message)

    default_command = acc_group.command("default", force_whitespace=True)

    @default_command.handle()
    async def handle_default(event: Event, args: Message = CommandArg()):
        user_id = event.get_user_id()
        text = args.extract_plain_text().strip()
        if not text:
            await default_command.finish("用法：/acc default show | /acc default set <lxns_account_key>")

        parts = text.split()
        action = parts[0].lower()

        if action == "show":
            gp = await get_default_lxns_game_profile_by_qq(user_id)
            if gp is None:
                await default_command.finish("尚未绑定 LXNS 账号")

            await default_command.finish(
                "当前默认账号：\n"
                + f"- lxns_account_key: {gp.account.account_name}\n" # type: ignore
                + f"- maimai_friend_code: {gp.maimai_name or ''}" # type: ignore
            )

        if action == "set":
            if len(parts) < 2:
                await default_command.finish("用法：/acc default set <lxns_account_key>")

            account_key = parts[1]
            await set_default_lxns_account_for_qq(qq=user_id, lxns_account_key=account_key)
            await default_command.finish("默认账号已更新")

        await default_command.finish("用法：/acc default show | /acc default set <lxns_account_key>")

    list_command = acc_group.command("list", force_whitespace=True)

    @list_command.handle()
    async def handle_list(event: Event):
        user_id = event.get_user_id()

        qq_link = await UserAccount.get_or_none(platform=QQ_PLATFORM, account_key=user_id).prefetch_related("user")
        if qq_link is None:
            await list_command.finish("尚未绑定 LXNS 账号")

        lxns_accounts = await UserAccount.filter(user=qq_link.user, platform="lxns").order_by("id") # type: ignore
        if not lxns_accounts:
            await list_command.finish("尚未绑定 LXNS 账号")

        lines: list[str] = []
        for acc in lxns_accounts:
            gp = await GameProfile.get_or_none(account=acc)
            friend_code = gp.maimai_friend_code if gp else ""
            lines.append(f"- {acc.account_key}  {friend_code}")

        logger.debug(f"[acc.list] qq={user_id} accounts={len(lxns_accounts)}")
        await list_command.finish("已绑定账号：\n" + "\n".join(lines))
