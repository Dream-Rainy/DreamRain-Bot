from __future__ import annotations

import asyncio
import re
from datetime import timedelta
from urllib.parse import parse_qs, urlparse

from nonebot import on_message
from nonebot.adapters import Event, Message
from nonebot.log import logger
from nonebot.matcher import Matcher
from nonebot.params import CommandArg
from nonebot.rule import Rule

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


_OAUTH_CODE_PATTERN = re.compile(r"^[A-Za-z0-9._~+/=-]{8,512}$")
_OAUTH_CODE_PREFIX_PATTERN = re.compile(r"^code(?:\s+|[:：]\s*)(?P<code>\S+)$", re.IGNORECASE)


def _query_states_match(query: str, expected_state: str | None) -> bool:
    if expected_state is None:
        return True

    states = [item.strip() for item in parse_qs(query).get("state", []) if item.strip()]
    return not states or expected_state in states


def _extract_oauth_code_from_text(text: str, *, expected_state: str | None = None) -> str | None:
    """Extract a manual OAuth code from plain text, a query string, or a callback URL."""
    text = text.strip()
    if not text:
        return None

    prefix_match = _OAUTH_CODE_PREFIX_PATTERN.match(text)
    if prefix_match:
        return prefix_match.group("code").strip()

    normalized_query = "&".join(part.strip() for part in text.splitlines() if part.strip())
    if not _query_states_match(normalized_query, expected_state):
        return None

    candidates = [normalized_query, text, *text.split()]

    for candidate in candidates:
        parsed = urlparse(candidate)
        queries = []
        if parsed.query:
            queries.append(parsed.query)
        if "=" in candidate:
            queries.append(candidate[1:] if candidate.startswith("?") else candidate)

        for query in queries:
            params = parse_qs(query)
            code = next((item.strip() for item in params.get("code", []) if item.strip()), "")
            if not code:
                continue
            if not _query_states_match(query, expected_state):
                continue
            return code

    if _OAUTH_CODE_PATTERN.fullmatch(text):
        return text

    return None


def _destroy_matcher(matcher: type[Matcher]) -> None:
    try:
        matcher.destroy()
    except ValueError:
        pass


def _register_manual_oauth_code_waiter(
    *,
    user_id: str,
    session_id: str,
    state: str,
    timeout_seconds: int,
) -> tuple[asyncio.Future[str], type[Matcher]]:
    future: asyncio.Future[str] = asyncio.get_running_loop().create_future()

    async def is_manual_oauth_code(event: Event) -> bool:
        if event.get_user_id() != user_id or event.get_session_id() != session_id:
            return False
        return _extract_oauth_code_from_text(event.get_plaintext(), expected_state=state) is not None

    manual_code_matcher = on_message(
        rule=Rule(is_manual_oauth_code),
        priority=1,
        block=True,
        expire_time=timedelta(seconds=timeout_seconds),
    )

    @manual_code_matcher.handle()
    async def handle_manual_oauth_code(event: Event):
        code = _extract_oauth_code_from_text(event.get_plaintext(), expected_state=state)
        if code and not future.done():
            future.set_result(code)
        await manual_code_matcher.finish("已收到授权码，正在完成 OAuth 绑定...")

    return future, manual_code_matcher


async def _wait_for_oauth_code_from_sse_or_message(
    *,
    event: Event,
    user_id: str,
    state: str,
    timeout_seconds: int,
) -> str | None:
    sse_future = sse_client.register(state)
    manual_future, manual_matcher = _register_manual_oauth_code_waiter(
        user_id=user_id,
        session_id=event.get_session_id(),
        state=state,
        timeout_seconds=timeout_seconds,
    )

    try:
        done, pending = await asyncio.wait(
            {sse_future, manual_future},
            timeout=timeout_seconds,
            return_when=asyncio.FIRST_COMPLETED,
        )
        for pending_future in pending:
            pending_future.cancel()
        if not done:
            return None

        completed = done.pop()
        if completed.cancelled():
            return None
        return completed.result()
    finally:
        sse_client.unregister(state)
        _destroy_matcher(manual_matcher)
        if not manual_future.done():
            manual_future.cancel()


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
            text="已生成 OAuth 授权链接，请在浏览器中打开完成授权：\n"
            + f"{bind_uri}\n"
            + "也可以直接在当前会话发送授权后的 code 或包含 code 的回调 URL。",
            reply_to=event.message_id,
        ))

        code = await _wait_for_oauth_code_from_sse_or_message(
            event=event,
            user_id=user_id,
            state=state,
            timeout_seconds=oa_client.state_ttl_seconds,
        )
        if code is None:
            await finish_with(BotResponse(text="OAuth 绑定超时，请重试", reply_to=event.message_id))

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
                + f"- lxns_account_key: {gp.account_key}\n"
                + f"- account_name: {gp.account_name}\n"
                + f"- maimai_friend_code: {gp.maimai_friend_code or ''}"
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
