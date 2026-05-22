import traceback
from typing import Any

from nonebot import logger

from ..views import mai_bg_draw
from ..services.song_query import search_song, MatchType
from ..services.collections import fetch_and_update_collections
from ....shared.bot_response import BotResponse
from ....shared.search.result_message import build_fuzzy_list_message, build_match_hint_text


async def song_info(song_query: Any, user_id: str, message_id: int) -> BotResponse:
    """查询乐曲信息并生成图片。

    支持多种查询方式：
    - 数字 ID: 如 146
    - 精确标题: 如 "39"
    - 别名: 如 "标39"
    - 模糊搜索: 如 "初音"
    """
    logger.debug(f"查询乐曲信息: query={song_query}, user={user_id}")

    results = await search_song(song_query)

    early_exit = build_fuzzy_list_message(results, message_id, not_found_text="未找到该乐曲信息")
    if early_exit:
        return early_exit

    perfect = [r for r in results if r.match_score == 100.0]
    fuzzy   = [r for r in results if r.match_score < 100.0]

    result = perfect[0] if perfect else results[0]
    song_id = result.song_id
    song_data = result.song_data

    logger.info(f"找到乐曲: [{song_id}] {song_data.title}")

    collections = await fetch_and_update_collections(song_id)
    if collections:
        song_data.collections = collections
        logger.debug(f"已加载 {len(collections)} 项收藏信息")

    hint = build_match_hint_text(perfect, fuzzy)
    try:
        song_info_img = await mai_bg_draw.render_song_info_img(song_data)
        return BotResponse(image=song_info_img, reply_to=message_id, suffix=hint)
    except Exception as e:
        traceback.print_exc()
        logger.error(f"渲染乐曲信息图片失败: {e}")
        return BotResponse(text=f"渲染图片失败: {str(e)}", reply_to=message_id)
