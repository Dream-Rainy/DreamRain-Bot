"""CHUNITHM 随机乐曲：支持按难度范围筛选。

难度等级说明与 maimai 相同：
- 整数级别（如 13）：定数范围为 X.0 ~ X.5
- 加号级别（如 13+）：定数范围为 X.6 ~ X.9
- internalLevelValue 字段为实际定数
"""

import random
import traceback
from typing import Optional, Tuple

from nonebot import logger

from ....shared.bot_response import BotResponse
from ..views.chuni_bg_draw import render_chuni_song_info_img
from ....integrations.lxns.plugin_data import plugin_data

# 难度名称（按索引）
_LEVEL_NAMES = ["BASIC", "ADVANCED", "EXPERT", "MASTER", "ULTIMA"]


def parse_difficulty_range(range_str: str) -> Optional[Tuple[float, float]]:
    """解析难度范围字符串，与 maimai 规则一致。

    - "13"   → [13.0, 13.5]
    - "13+"  → [13.6, 13.9]
    - "13.5" → [13.5, 13.5]
    - "12-13" / "12+-13+" / "12.5-13.5" → 对应范围
    """
    range_str = range_str.strip()

    def parse_single(s: str) -> Optional[Tuple[float, float]]:
        s = s.strip()
        if s.endswith("+"):
            try:
                base = float(s[:-1])
                return (base + 0.6, base + 0.9)
            except ValueError:
                return None
        else:
            try:
                value = float(s)
                if value == int(value):
                    return (value, value + 0.5)
                return (value, value)
            except ValueError:
                return None

    if "-" in range_str:
        parts = range_str.split("-", 1)
        if len(parts) == 2:
            lo = parse_single(parts[0])
            hi = parse_single(parts[1])
            if lo and hi:
                min_ds, _ = lo
                _, max_ds = hi
                if min_ds <= max_ds:
                    return (min_ds, max_ds)
        return None

    return parse_single(range_str)


def get_chuni_songs_by_difficulty_range(min_ds: float, max_ds: float) -> list[dict]:
    """筛选 internalLevelValue 在指定范围内的 CHUNITHM 谱面。

    Returns:
        list of {
            "song_data": dict,
            "sheet": dict,
            "song_type": str,   # "standard" / "ultima"
            "level_index": int,
            "level_name": str,
            "level_value": float,
        }
    """
    matching = []

    for song_id, song in plugin_data.chuni_song_data.items():
        difficulties: dict = song.difficulties or {}

        for song_type in ("standard", "ultima"):
            sheets = difficulties.get(song_type) or []
            for idx, sheet in enumerate(sheets):
                if not isinstance(sheet, dict):
                    continue
                lv = sheet.get("internalLevelValue")
                if lv is None:
                    lv = sheet.get("levelValue")
                if lv is None:
                    continue
                try:
                    lv = float(lv)
                except (TypeError, ValueError):
                    continue

                if min_ds <= lv <= max_ds:
                    matching.append({
                        "song_data": song,
                        "sheet": sheet,
                        "song_type": song_type,
                        "level_index": idx,
                        "level_name": _LEVEL_NAMES[idx] if idx < len(_LEVEL_NAMES) else f"LV{idx}",
                        "level_value": lv,
                    })

    return matching


async def chuni_random_song(range_str: Optional[str], user_id: str, message_id: int) -> BotResponse:
    """随机选择一首 CHUNITHM 乐曲并返回谱面图。"""
    logger.debug(f"[chuni] 随机乐曲: range={range_str!r}, user={user_id}")

    if range_str:
        diff_range = parse_difficulty_range(range_str)
        if diff_range is None:
            return BotResponse(
                text=(
                    "难度范围格式错误\n"
                    "支持的格式：\n"
                    "• 整数：13 (定数13.0~13.5)\n"
                    "• 加号：13+ (定数13.6~13.9)\n"
                    "• 精确：13.5 (定数13.5)\n"
                    "• 范围：12-13 或 12-13+ 或 12.5-13.5"
                ),
                reply_to=message_id,
            )
        min_ds, max_ds = diff_range
    else:
        min_ds, max_ds = 0.0, float("inf")

    matching = get_chuni_songs_by_difficulty_range(min_ds, max_ds)

    if not matching:
        if range_str:
            return BotResponse(
                text=f"未找到难度范围在 {range_str} 的 CHUNITHM 乐曲",
                reply_to=message_id,
            )
        return BotResponse(
            text="CHUNITHM 曲库数据为空，请联系管理员更新数据",
            reply_to=message_id,
        )

    selected = random.choice(matching)
    song_data = selected["song_data"]
    song_id = song_data.id

    logger.info(
        f"[chuni] 随机到乐曲: [{song_id}] {song_data.title} "
        f"[{selected['song_type'].upper()} {selected['level_name']}] "
        f"定数: {selected['level_value']}"
    )

    try:
        img = await render_chuni_song_info_img(song_data)

        range_text = f" (定数: {selected['level_value']})" if range_str else ""
        description = (
            f"\n🎲 随机到的 CHUNITHM 乐曲{range_text}：\n"
            f"[{song_id}] {song_data.title}\n"
            f"[{selected['song_type'].upper()} {selected['level_name']} "
            f"{selected['sheet'].get('level', str(selected['level_value']))}]"
        )

        return BotResponse(text=description, image=img, reply_to=message_id)
    except Exception as e:
        traceback.print_exc()
        logger.error(f"[chuni] 渲染随机乐曲失败: {e}")
        return BotResponse(text=f"渲染图片失败: {e!s}", reply_to=message_id)
