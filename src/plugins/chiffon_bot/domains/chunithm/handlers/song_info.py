"""CHUNITHM 乐曲查询与图片渲染（数据与检索在 ``maimai.services.song_query``）。"""

import traceback

from nonebot import logger

from ...maimai.services.song_query import search_song
from ..views.chuni_bg_draw import render_chuni_song_info_img
from ....shared.bot_response import BotResponse
from ....shared.search.result_message import build_fuzzy_list_message, build_match_hint_text


async def chuni_song_info_msg(song_query: str | int, message_id: int) -> BotResponse:
    """按 ID / 标题 / 别名查询 CHUNITHM 乐曲并返回含渲染图的 ``BotResponse``。"""
    logger.debug(f"[chuni] 查询乐曲: query={song_query!r}")

    results = await search_song(song_query, game_code="chunithm")

    early_exit = build_fuzzy_list_message(results, message_id, not_found_text="未找到该 CHUNITHM 乐曲")
    if early_exit:
        return early_exit

    perfect = [r for r in results if r.match_score == 100.0]
    fuzzy = [r for r in results if r.match_score < 100.0]

    result = perfect[0] if perfect else results[0]
    song_id = result.song_id
    song_data = result.song_data

    logger.info(f"[chuni] 命中乐曲: [{song_id}] {result.title}")

    hint = build_match_hint_text(perfect, fuzzy)
    try:
        img = await render_chuni_song_info_img(song_data)
        return BotResponse(image=img, reply_to=message_id, suffix=hint)
    except Exception as e:
        traceback.print_exc()
        logger.error(f"[chuni] 渲染失败: {e}")
        return BotResponse(text=f"渲染图片失败: {e!s}", reply_to=message_id)
