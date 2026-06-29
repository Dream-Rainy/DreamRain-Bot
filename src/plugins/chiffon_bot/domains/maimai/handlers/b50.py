import time

from nonebot import logger

from arcade_helper import MaimaiPlayer

from ....shared.bot_response import BotResponse
from ..views import mai_bg_draw
from ..services.score_utils import enhance_scores
from ._timing import format_timing_msg


async def b50(player: MaimaiPlayer, headers: dict, user_id: str, message_id: int) -> BotResponse:
    logger.debug(f"查询 B50: friend_code={player.friend_code}, user={user_id}")
    T = {}
    T["total_start"] = time.perf_counter()

    t_fetch = time.perf_counter()
    user_data = (await player.profile(headers=headers)).data.raw

    b50_data = (await player.bests(headers=headers)).data.raw
    b35_data = await enhance_scores(b50_data["data"]["standard"])
    b15_data = await enhance_scores(b50_data["data"]["dx"])
    T["fetch_data"] = time.perf_counter() - t_fetch

    if b50_data["code"] != 200:
        logger.warning(f"查询 B50 失败: {player.friend_code} - {b50_data['message']}")
        return BotResponse(text=f"查询失败, {b50_data['message']}")

    t_render = time.perf_counter()
    b50_img = await mai_bg_draw.render_b50_img(
        user_data=user_data, b35_data=b35_data, b15_data=b15_data
    )
    T["render_bg"] = time.perf_counter() - t_render

    T["total"] = time.perf_counter() - T["total_start"]

    timing_msg = format_timing_msg(T["fetch_data"], T["render_bg"], T["total"])

    return BotResponse(image=b50_img, reply_to=message_id, suffix=timing_msg)
