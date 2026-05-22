"""跨游戏自然语言查歌。

触发模式：XXX是什么歌 / XXX是啥歌
逻辑：
- 同时在 maimai 和 CHUNITHM 中检索
- 比较两侧最佳结果的命中优先级（id > 标题完全 > 别名完全 > 标题模糊 > 别名模糊）
  - 一侧优先级更高 → 直接返回该游戏结果
  - 同级 → 消歧义提示
  - 一侧无结果 → 直接返回另一侧
  - 两侧均无结果 → 静默
"""

from __future__ import annotations

import asyncio
import re

from nonebot import on_message
from nonebot.adapters import Event
from nonebot.log import logger
from nonebot.params import EventPlainText

from ...domains.maimai.handlers.song_info import song_info as mai_song_info
from ...domains.chunithm.handlers.song_info import chuni_song_info_msg
from ...domains.maimai.services.song_query import search_song
from ...shared.bot_response import BotResponse
from ...shared.search.song_query import MatchType, SongQueryResult
from ._response import finish_with

# ── 优先级映射（数值越小优先级越高）────────────────────────────────────────
_PRIORITY: dict[MatchType, int] = {
    MatchType.EXACT_ID:        0,   # id
    MatchType.EXACT_TITLE:     1,   # 标题完全命中
    MatchType.EXACT_ALIAS:     2,   # 别名完全命中
    MatchType.FUZZY_TITLE:     3,   # 标题模糊命中
    MatchType.PINYIN_INITIALS: 3,   # 拼音首字母 → 同属标题模糊
    MatchType.PINYIN_FULL:     3,   # 完整拼音   → 同属标题模糊
    MatchType.SIMPLIFIED:      3,   # 简体化归一 → 同属标题模糊
    MatchType.FUZZY_ALIAS:     4,   # 别名模糊命中
}

_SONG_PATTERNS = [
    r"^(.+?)是什么歌[？?]?$",
    r"^(.+?)是啥歌[？?]?$",
]


def _best_priority(results: list[SongQueryResult]) -> int | None:
    """返回结果列表中最高优先级的级别（None 表示列表为空）。"""
    if not results:
        return None
    return min(_PRIORITY.get(r.match_type, 99) for r in results)


def _build_conflict_message(
    query: str,
    mai_r: SongQueryResult,
    chuni_r: SongQueryResult,
    message_id: int,
) -> BotResponse:
    lines = [
        "在多个游戏中找到匹配，请指定游戏：",
        f"① [maimai]   [{mai_r.song_id}] {mai_r.title}",
        f"② [CHUNITHM] [{chuni_r.song_id}] {chuni_r.title}",
        "",
        f"/mai.song {query}   或   /chuni.song {query}",
    ]
    return BotResponse(text="\n".join(lines), reply_to=message_id)


def register_natural_language_commands():
    song_query_handler = on_message(priority=10, block=False)

    @song_query_handler.handle()
    async def handle_cross_game_song_query(event: Event, plain_text: str = EventPlainText()):
        text = plain_text.strip()

        song_query: str | None = None
        for pattern in _SONG_PATTERNS:
            m = re.match(pattern, text)
            if m:
                song_query = m.group(1).strip()
                break

        if not song_query or not (1 <= len(song_query) <= 50):
            return

        logger.info(f"[NL] 跨游戏查歌: {song_query!r}")

        mai_results, chuni_results = await asyncio.gather(
            search_song(song_query, game_code="maimai"),
            search_song(song_query, game_code="chunithm"),
        )

        mai_prio = _best_priority(mai_results)
        chuni_prio = _best_priority(chuni_results)

        user_id = event.get_user_id()
        message_id = event.message_id

        # 两侧均无结果 → 返回未找到匹配的歌曲
        if mai_prio is None and chuni_prio is None:
            await finish_with(BotResponse(text="未找到匹配的歌曲", reply_to=message_id))

        # 只有一侧有结果 → 直接返回
        if mai_prio is None:
            logger.info(f"[NL] 仅 CHUNITHM 命中 (prio={chuni_prio}): [{chuni_results[0].song_id}] {chuni_results[0].title}")
            await finish_with(await chuni_song_info_msg(song_query, message_id))

        if chuni_prio is None:
            logger.info(f"[NL] 仅 maimai 命中 (prio={mai_prio}): [{mai_results[0].song_id}] {mai_results[0].title}")
            await finish_with(await mai_song_info(song_query, user_id, message_id))

        # 两侧均有结果 → 比较优先级
        if mai_prio < chuni_prio:
            logger.info(f"[NL] maimai 优先级更高 ({mai_prio} < {chuni_prio}): [{mai_results[0].song_id}] {mai_results[0].title}")
            await finish_with(await mai_song_info(song_query, user_id, message_id))

        if chuni_prio < mai_prio:
            logger.info(f"[NL] CHUNITHM 优先级更高 ({chuni_prio} < {mai_prio}): [{chuni_results[0].song_id}] {chuni_results[0].title}")
            await finish_with(await chuni_song_info_msg(song_query, message_id))

        # 同优先级 → 消歧义
        logger.info(
            f"[NL] 同优先级冲突 (prio={mai_prio}): "
            f"mai=[{mai_results[0].song_id}]{mai_results[0].title} "
            f"chuni=[{chuni_results[0].song_id}]{chuni_results[0].title}"
        )
        response = _build_conflict_message(song_query, mai_results[0], chuni_results[0], message_id)
        await finish_with(response)
