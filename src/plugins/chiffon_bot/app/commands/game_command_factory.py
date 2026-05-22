"""通用命令工厂 — 基于 DomainAdapter 一键注册游戏命令。

每个游戏只需调用 ``register_game_commands(group, adapter)`` 即可获得：
help / song / alias / random / update / clean + 自然语言随机查询
"""

from __future__ import annotations

import re

from nonebot import on_message, logger
from nonebot.adapters import Event, Message
from nonebot.params import CommandArg, EventPlainText
from nonebot.permission import SUPERUSER

from ...shared.domain_adapter import DomainAdapter
from ...shared.handlers.generic_random_song import generic_random_song, parse_difficulty_range
from ...shared.handlers.generic_song_info import generic_song_info
from ...shared.search.song_query import get_song_aliases
from ._response import finish_with


def register_game_commands(group, adapter: DomainAdapter) -> None:
    """为一组命令前缀注册该游戏的所有标准命令。

    Args:
        group: NoneBot 命令组（如 ``maimai_group`` / ``chuni_group``）。
        adapter: 该游戏的 ``DomainAdapter`` 实现。
    """
    gc = adapter.game_code

    # ── help ──────────────────────────────────────────────────────────────
    help_cmd = group.command("help", force_whitespace=True)

    @help_cmd.handle()
    async def _help():
        await help_cmd.finish(
            f"[{adapter.display_name}] 帮助\n"
            f"查询乐曲信息：/{gc}.song [歌曲名/ID]\n"
            f"查询乐曲别名：/{gc}.alias [歌曲名/ID]\n"
            f"随机乐曲：/{gc}.random [难度范围]\n"
            f"  示例：13(定数13.0~13.5) / 13+(13.6~13.9)\n"
            f"       12-13 / 13.5 / 12-13+\n"
        )

    # ── song ──────────────────────────────────────────────────────────────
    song_cmd = group.command("song", force_whitespace=True)

    @song_cmd.handle()
    async def _song(event: Event, args: Message = CommandArg()):
        query = args.extract_plain_text().strip()
        if not query:
            await song_cmd.finish(f"查询条件不可以为空哟，例如：/{gc}.song 1")
        response = await generic_song_info(query, event.get_user_id(), event.message_id, adapter)
        await finish_with(response)

    # ── alias ─────────────────────────────────────────────────────────────
    alias_cmd = group.command("alias", force_whitespace=True)

    @alias_cmd.handle()
    async def _alias(event: Event, args: Message = CommandArg()):
        query = args.extract_plain_text().strip()
        if not query:
            await alias_cmd.finish(f"请输入要查询的歌曲名或 ID，例如：/{gc}.alias 1")

        result = await get_song_aliases(query, game_code=gc)
        if not result:
            from ....shared.bot_response import BotResponse
            await finish_with(BotResponse(
                text=f" 未找到 {adapter.display_name} 歌曲：{query}",
                reply_to=event.message_id,
            ))
            return

        song_id = result["song_id"]
        title = result["title"]
        aliases = result["aliases"]

        if not aliases:
            response = f"[{song_id}] {title}\n\n暂无别名数据"
        else:
            alias_list = "\n".join(f"  · {a}" for a in aliases)
            response = (
                f"[{song_id}] {title}\n"
                f"──────────\n"
                f"别名列表（共 {len(aliases)} 个）：\n"
                f"{alias_list}"
            )

        from ....shared.bot_response import BotResponse
        await finish_with(BotResponse(text=response, reply_to=event.message_id))

    # ── random ────────────────────────────────────────────────────────────
    random_cmd = group.command("random", force_whitespace=True)

    @random_cmd.handle()
    async def _random(event: Event, args: Message = CommandArg()):
        range_str = args.extract_plain_text().strip() or None
        response = await generic_random_song(range_str, event.get_user_id(), event.message_id, adapter)
        await finish_with(response)

    # ── update (SUPERUSER) ────────────────────────────────────────────────
    update_cmd = group.command("update", force_whitespace=True, permission=SUPERUSER)

    @update_cmd.handle()
    async def _update():
        try:
            from ...domains.maimai.services.song_data_updater import refresh_song_data
            is_updated, message = await refresh_song_data()
        except Exception as e:
            message = f"更新失败: {e}"
        await update_cmd.finish(message)

    # ── clean (SUPERUSER) ─────────────────────────────────────────────────
    clean_cmd = group.command("clean", force_whitespace=True, permission=SUPERUSER)

    @clean_cmd.handle()
    async def _clean():
        adapter.clear_image_cache()
        await clean_cmd.finish(f"{adapter.display_name} 图片缓存已清除")

    # ── 自然语言随机查询 ──────────────────────────────────────────────────
    _register_natural_random(group, adapter)


def _register_natural_random(group, adapter: DomainAdapter) -> None:
    """注册该游戏的自然语言随机乐曲查询。"""
    gc = adapter.game_code

    natural = on_message(priority=10, block=False)

    # 构建游戏特定的随机模式
    if gc == "chunithm":
        patterns = [
            (rf"^{gc}随机(?:一首)?(?:歌|乐曲|曲子)?[？?]?$", None),
            (rf"^随机(?:一首)?{gc}(?:歌|乐曲|曲子)?[？?]?$", None),
            (rf"^{gc}随机([0-9.]+\+?)(?:难度)?(?:的)?(?:歌|乐曲|曲子)?[？?]?$", 1),
            (rf"^{gc}随机([0-9.]+)-([0-9.]+)(?:难度)?(?:的)?(?:歌|乐曲|曲子)?[？?]?$", 2),
            (rf"^{gc}随机([0-9.]+)到([0-9.]+)(?:难度)?(?:的)?(?:歌|乐曲|曲子)?[？?]?$", 2),
        ]
    else:
        patterns = [
            (r"^随机(?:一首)?(?:歌|乐曲|曲子)?[？?]?$", None),
            (r"^来首?随机(?:歌|乐曲|曲子)?[？?]?$", None),
            (r"^(?:随机|来首?)(?:一首)?([0-9.]+\+?)(?:难度)?(?:的)?(?:歌|乐曲|曲子)?[？?]?$", 1),
            (r"^(?:随机|来首?)(?:一首)?([0-9.]+)-([0-9.]+)(?:难度)?(?:的)?(?:歌|乐曲|曲子)?[？?]?$", 2),
            (r"^(?:随机|来首?)(?:一首)?([0-9.]+)到([0-9.]+)(?:难度)?(?:的)?(?:歌|乐曲|曲子)?[？?]?$", 2),
        ]

    @natural.handle()
    async def _natural_random(event: Event, plain_text: str = EventPlainText()):
        text = plain_text.strip()

        for pattern, last_index in patterns:
            m = re.match(pattern, text, re.IGNORECASE)
            if not m:
                continue

            range_str: str | None = None
            if last_index is not None:
                if last_index == 1:
                    range_str = m.group(1)
                elif last_index == 2:
                    range_str = f"{m.group(1)}-{m.group(2)}"

            logger.info(f"[{gc}] 自然语言随机乐曲: {text!r} -> 难度: {range_str!r}")
            response = await generic_random_song(range_str, event.get_user_id(), event.message_id, adapter)
            await finish_with(response)
