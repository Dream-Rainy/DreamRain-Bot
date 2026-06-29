"""通用歌曲信息查询 Handler — 基于 DomainAdapter 消除 maimai/chunithm 重复代码。"""

from __future__ import annotations

import traceback

from nonebot import logger

from ..bot_response import BotResponse
from ..game.adapter import DomainAdapter
from ..search.catalog_search import search_song_with_audit
from ..search.result_message import build_fuzzy_list_message, build_match_hint_text


async def generic_song_info(
    song_query: str | int,
    user_id: str,
    message_id: int,
    adapter: DomainAdapter,
) -> BotResponse:
    """通用歌曲信息查询：搜索 → 拉取收藏 → 渲染 → 返回消息。"""
    gc = adapter.game_code
    logger.debug(f"[{gc}] 查询乐曲: query={song_query!r}")

    results = await search_song_with_audit(song_query, game_code=gc)

    not_found = f"未找到该 {adapter.display_name} 乐曲"
    early_exit = build_fuzzy_list_message(results, message_id, not_found_text=not_found)
    if early_exit:
        return early_exit

    perfect = [r for r in results if r.match_score == 100.0]
    fuzzy = [r for r in results if r.match_score < 100.0]

    result = perfect[0] if perfect else results[0]
    song_id = result.song_id
    song_data = result.song_data

    logger.info(f"[{gc}] 命中乐曲: [{song_id}] {result.title}")

    # 可选：拉取收藏信息
    collections = await adapter.fetch_collections(song_id)
    if collections:
        song_data.collections = collections  # type: ignore[attr-defined]

    # 渲染 & 返回
    hint = build_match_hint_text(perfect, fuzzy)
    try:
        img = await adapter.render_song_image(song_data)
        return BotResponse(image=img, reply_to=message_id, suffix=hint)
    except Exception as e:
        traceback.print_exc()
        logger.error(f"[{gc}] 渲染乐曲信息图片失败: {e}")
        return BotResponse(text=f"渲染图片失败: {e!s}", reply_to=message_id)
