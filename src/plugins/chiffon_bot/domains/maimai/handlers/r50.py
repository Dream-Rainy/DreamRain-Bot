import time

from nonebot import logger

from arcade_helper import MaimaiPlayer

from ....shared.bot_response import BotResponse
from ..views import mai_bg_draw
from ..services.score_utils import enhance_scores
from ._timing import format_timing_msg


async def r50(player: MaimaiPlayer, headers: dict, user_id: str, message_id: int) -> BotResponse:
    logger.debug(f"查询 R50: friend_code={player.friend_code}, user={user_id}")
    T = {}
    T["total_start"] = time.perf_counter()

    t_fetch = time.perf_counter()
    try:
        user_data = (await player.profile(headers=headers)).data.raw
        recent_data = (await player.recents(headers=headers)).data
    except Exception as exc:
        logger.warning(f"查询 R50 失败: {player.friend_code} - {exc}")
        return BotResponse(text="查询失败，请稍后重试。", reply_to=message_id)

    for payload in (user_data, recent_data.model_extra or {}):
        if payload.get("code", 200) != 200 or payload.get("success") is False:
            return BotResponse(text=f"查询失败, {payload.get('message', '查分器返回异常')}", reply_to=message_id)

    recent_scores = await enhance_scores([score.raw for score in recent_data.scores])
    T["fetch_data"] = time.perf_counter() - t_fetch

    t_render = time.perf_counter()
    r50_img = await mai_bg_draw.render_r50_img(
        user_data={"data": user_data}, recent_data=recent_scores
    )
    T["render_bg"] = time.perf_counter() - t_render

    T["total"] = time.perf_counter() - T["total_start"]

    timing_msg = format_timing_msg(T["fetch_data"], T["render_bg"], T["total"])

    return BotResponse(image=r50_img, reply_to=message_id, suffix=timing_msg)
