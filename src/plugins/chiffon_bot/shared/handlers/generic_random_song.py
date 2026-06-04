"""通用随机选曲 Handler — 基于 DomainAdapter 消除 maimai/chunithm 重复代码。

``parse_difficulty_range`` 两个游戏完全一致，提取到此。
"""

from __future__ import annotations

import random
import traceback
from typing import Mapping, Optional

from nonebot import logger

from ..bot_response import BotResponse
from ..game.adapter import DomainAdapter
from ..song_data import SongData


def parse_difficulty_range(range_str: str) -> tuple[float, float] | None:
    """解析难度范围字符串。

    规则（与 maimai/chunithm 一致）：
    - ``"13"``  → [13.0, 13.5]
    - ``"13+"`` → [13.6, 13.9]
    - ``"13.5"``→ [13.5, 13.5]
    - ``"12-13"`` / ``"12+-13+"`` / ``"12.5-13.5"`` → 对应范围
    """

    def _parse_single(s: str) -> tuple[float, float] | None:
        s = s.strip()
        if s.endswith("+"):
            try:
                base = float(s[:-1])
                return (base + 0.6, base + 0.9)
            except ValueError:
                return None
        try:
            value = float(s)
            if value == int(value):
                return (value, value + 0.5)
            return (value, value)
        except ValueError:
            return None

    range_str = range_str.strip()
    if "-" in range_str:
        parts = range_str.split("-", 1)
        if len(parts) == 2:
            lo = _parse_single(parts[0])
            hi = _parse_single(parts[1])
            if lo and hi:
                min_ds, _ = lo
                _, max_ds = hi
                if min_ds <= max_ds:
                    return (min_ds, max_ds)
        return None

    return _parse_single(range_str)


def _pick_level_value(sheet: dict | object) -> float | None:
    """从谱面中提取定数值（兼容 dict 和 Pydantic 模型）。"""
    if isinstance(sheet, dict):
        lv = sheet.get("internalLevelValue")
        if lv is None:
            lv = sheet.get("levelValue")
    else:
        lv = getattr(sheet, "internal_level_value", None)
        if lv is None:
            lv = getattr(sheet, "level_value", None)
    if lv is not None:
        try:
            return float(lv)
        except (TypeError, ValueError):
            pass
    return None


def get_songs_by_difficulty_range(
    store: Mapping[int, SongData],
    min_ds: float,
    max_ds: float,
    adapter: DomainAdapter,
) -> list[dict]:
    """从曲库中筛选指定难度范围内的所有谱面。

    Returns:
        list of {
            "song_data": SongData,
            "sheet": dict,
            "song_type": str,
            "level_index": int,
            "level_name": str,
            "level_value": float,
        }
    """
    matching: list[dict] = []
    level_names = adapter.level_names
    difficulty_types = adapter.difficulty_types

    for _song_id, song_data in store.items():
        difficulties = song_data.difficulties or {}

        for song_type in difficulty_types:
            sheets = difficulties.get(song_type) or []
            for idx, sheet in enumerate(sheets):
                lv = _pick_level_value(sheet)
                if lv is None:
                    continue
                if min_ds <= lv <= max_ds:
                    matching.append({
                        "song_data": song_data,
                        "sheet": sheet,
                        "song_type": song_type,
                        "level_index": idx,
                        "level_name": level_names[idx] if idx < len(level_names) else f"LV{idx}",
                        "level_value": lv,
                    })

    return matching


async def generic_random_song(
    range_str: str | None,
    user_id: str,
    message_id: int,
    adapter: DomainAdapter,
) -> BotResponse:
    """通用随机选曲：解析难度 → 筛选 → 随机选取 → 渲染 → 返回消息。"""
    gc = adapter.game_code
    logger.debug(f"[{gc}] 随机乐曲: range={range_str!r}, user={user_id}")

    # 1. 解析难度范围
    if range_str:
        diff_range = parse_difficulty_range(range_str)
        if diff_range is None:
            return BotResponse(
                text=(
                    "难度范围格式错误\n"
                    "支持的格式：\n"
                    "· 整数：13 (定数13.0~13.5)\n"
                    "· 加号：13+ (定数13.6~13.9)\n"
                    "· 精确：13.5 (定数13.5)\n"
                    "· 范围：12-13 或 12-13+ 或 12.5-13.5"
                ),
                reply_to=message_id,
            )
        min_ds, max_ds = diff_range
    else:
        min_ds, max_ds = 0.0, float("inf")

    # 2. 按需从数据库加载完整曲库候选，本次命令用完即释放
    store = await adapter.load_all_songs()
    matching = get_songs_by_difficulty_range(store, min_ds, max_ds, adapter)

    if not matching:
        if range_str:
            return BotResponse(
                text=f"未找到难度范围在 {range_str} 的 {adapter.display_name} 乐曲",
                reply_to=message_id,
            )
        return BotResponse(
            text=f"{adapter.display_name} 曲库数据为空，请联系管理员更新数据",
            reply_to=message_id,
        )

    # 3. 随机选取
    selected = random.choice(matching)
    song_data: SongData = selected["song_data"]
    song_id = song_data.id

    logger.info(
        f"[{gc}] 随机到乐曲: [{song_id}] {song_data.title} "
        f"[{selected['song_type'].upper()} {selected['level_name']}] "
        f"定数: {selected['level_value']}"
    )

    # 4. 可选：拉取收藏信息
    collections = await adapter.fetch_collections(song_id)
    if collections:
        song_data.collections = collections  # type: ignore[attr-defined]

    # 5. 渲染 & 返回
    try:
        img = await adapter.render_song_image(song_data)

        range_text = f" (定数: {selected['level_value']})" if range_str else ""
        sheet = selected["sheet"]
        if isinstance(sheet, dict):
            level = sheet.get("level")
        else:
            level = getattr(sheet, "level", None)
        level_display = str(level or selected["level_value"])
        description = (
            f"\n随机到的 {adapter.display_name} 乐曲{range_text}：\n"
            f"[{song_id}] {song_data.title}\n"
            f"[{selected['song_type'].upper()} {selected['level_name']} {level_display}]"
        )

        return BotResponse(text=description, image=img, reply_to=message_id)
    except Exception as e:
        traceback.print_exc()
        logger.error(f"[{gc}] 渲染随机乐曲失败: {e}")
        return BotResponse(text=f"渲染图片失败: {e!s}", reply_to=message_id)
