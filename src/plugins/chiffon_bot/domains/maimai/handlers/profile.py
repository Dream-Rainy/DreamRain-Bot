import time

from nonebot import logger

from arcade_helper import MaimaiPlayer

from ....shared.bot_response import BotResponse
from ..views import mai_bg_draw
from ._timing import format_timing_msg


async def profile(player: MaimaiPlayer, headers: dict, user_id: str, message_id: int) -> BotResponse:
    logger.debug(f"查询个人资料: friend_code={player.friend_code}, user={user_id}")
    T = {}
    T["total_start"] = time.perf_counter()

    t_fetch = time.perf_counter()
    try:
        user_data = (await player.profile(headers=headers)).data.raw
    except Exception as exc:
        logger.warning(f"查询个人资料失败: {player.friend_code} - {exc}")
        return BotResponse(text="查询失败，请稍后重试。", reply_to=message_id)

    T["fetch_data"] = time.perf_counter() - t_fetch

    if user_data.get("code", 200) != 200 or user_data.get("success") is False:
        return BotResponse(text=f"查询失败, {user_data.get('message', '查分器返回异常')}", reply_to=message_id)

    t_render = time.perf_counter()
    profile_img = await mai_bg_draw.render_b50_img(user_data={"data": user_data}, height=536)
    T["render_bg"] = time.perf_counter() - t_render

    T["total"] = time.perf_counter() - T["total_start"]

    timing_msg = format_timing_msg(T["fetch_data"], T["render_bg"], T["total"])

    return BotResponse(image=profile_img, reply_to=message_id, suffix=timing_msg)
