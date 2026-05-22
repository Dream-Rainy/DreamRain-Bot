import time

from nonebot import logger

from ....integrations.lxns.player_api import get_r50_data, get_user_data
from ....shared.bot_response import BotResponse
from ..views import mai_bg_draw
from ..services.score_utils import enhance_scores
from ._timing import format_timing_msg


async def r50(friend_code: str, headers: dict, user_id: str, message_id: int) -> BotResponse:
    logger.debug(f"查询 R50: friend_code={friend_code}, user={user_id}")
    T = {}
    T["total_start"] = time.perf_counter()

    t_fetch = time.perf_counter()
    user_data = await get_user_data(friend_code, headers)
    recent_data = await get_r50_data(friend_code, headers)
    if recent_data["code"] != 200:
        logger.warning(f"查询 R50 失败: {friend_code} - {recent_data['message']}")
        return BotResponse(text=f"查询失败, {recent_data['message']}")

    recent_data["data"] = await enhance_scores(recent_data["data"])
    T["fetch_data"] = time.perf_counter() - t_fetch

    t_render = time.perf_counter()
    r50_img = await mai_bg_draw.render_r50_img(
        user_data=user_data, recent_data=recent_data["data"]
    )
    T["render_bg"] = time.perf_counter() - t_render

    T["total"] = time.perf_counter() - T["total_start"]

    timing_msg = format_timing_msg(T["fetch_data"], T["render_bg"], T["total"])

    return BotResponse(image=r50_img, reply_to=message_id, suffix=timing_msg)
