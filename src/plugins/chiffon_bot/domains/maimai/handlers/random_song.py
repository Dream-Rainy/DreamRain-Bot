"""随机乐曲功能：支持按难度范围筛选。

难度等级说明：
- 整数级别（如 13）：定数范围为 X.0 ~ X.5（如 13.0 ~ 13.5）
- 加号级别（如 13+）：定数范围为 X.6 ~ X.9（如 13.6 ~ 13.9）
- level_value 字段为实际的浮点数定数值
"""

import random
import traceback
from typing import Optional, Tuple

from nonebot import logger

from ....shared.bot_response import BotResponse
from ..views import mai_bg_draw
from ..services.collections import fetch_and_update_collections
from ....integrations.lxns.plugin_data import plugin_data


def parse_difficulty_range(range_str: str) -> Optional[Tuple[float, float]]:
    """解析难度范围字符串。
    
    难度等级规则：
    - 整数级别（如 13）：定数范围 13.0 ~ 13.5
    - 加号级别（如 13+）：定数范围 13.6 ~ 13.9
    - 精确小数（如 13.5）：精确匹配 13.5
    
    支持的格式：
    - "13": 整数级别 -> [13.0, 13.5]
    - "13+": 加号级别 -> [13.6, 13.9]
    - "13.5": 精确小数 -> [13.5, 13.5]
    - "12-13": 范围 -> [12.0, 13.5]（结束值按整数级别规则）
    - "12+-13+": 范围 -> [12.6, 13.9]
    - "12.5-13.5": 精确范围 -> [12.5, 13.5]
    
    Args:
        range_str: 难度范围字符串
        
    Returns:
        (min_ds, max_ds) 元组，解析失败则返回 None
    """
    range_str = range_str.strip()
    
    def parse_single_value(s: str) -> Optional[Tuple[float, float]]:
        """解析单个难度值，返回其代表的范围"""
        s = s.strip()
        if s.endswith('+'):
            # "13+" -> [13.6, 13.9]
            try:
                base = float(s[:-1])
                return (base + 0.6, base + 0.9)
            except ValueError:
                return None
        else:
            try:
                value = float(s)
                # 判断是否为整数（没有小数部分）
                if value == int(value):
                    # "13" -> [13.0, 13.5]
                    return (value, value + 0.5)
                else:
                    # "13.5" -> [13.5, 13.5]
                    return (value, value)
            except ValueError:
                return None
    
    # 处理范围 "12-13" 或 "12+-13+" 或 "12.5-13.5"
    if '-' in range_str:
        parts = range_str.split('-', 1)
        if len(parts) == 2:
            min_result = parse_single_value(parts[0])
            max_result = parse_single_value(parts[1])
            
            if min_result and max_result:
                min_ds, _ = min_result
                _, max_ds = max_result
                if min_ds <= max_ds:
                    return (min_ds, max_ds)
        return None
    
    # 处理单个值 "13" 或 "13+" 或 "13.5"
    return parse_single_value(range_str)


def get_songs_by_difficulty_range(min_ds: float, max_ds: float) -> list[dict]:
    """获取指定难度范围内的所有乐曲及其对应难度。
    
    Args:
        min_ds: 最小难度值（包含）
        max_ds: 最大难度值（包含）
        
    Returns:
        符合条件的乐曲列表，每个元素包含乐曲数据和具体难度信息
        格式: [{
            "song_data": dict,      # 完整乐曲数据
            "difficulty": dict,     # 具体难度信息
            "song_type": str,       # "standard" 或 "dx"
            "level_index": int,     # 难度索引 (0-4)
            "level_value": float    # 实际难度值
        }]
    """
    matching_songs = []
    
    level_names = ["Basic", "Advanced", "Expert", "Master", "Re:Master"]
    
    for song_id, song_data in plugin_data.mai_song_data.items():
        difficulties = song_data.difficulties
        
        # 遍历两种谱面类型
        for song_type in ["standard", "dx"]:
            type_difficulties = difficulties.get(song_type, [])
            
            # 遍历每个难度级别
            for level_index, difficulty in enumerate(type_difficulties):
                # 获取难度值 (level_value)
                level_value = difficulty.internal_level_value
                if level_value is None:
                    continue
                
                # 检查是否在范围内
                if min_ds <= level_value <= max_ds:
                    matching_songs.append({
                        "song_data": song_data,
                        "difficulty": difficulty,
                        "song_type": song_type,
                        "level_index": level_index,
                        "level_name": level_names[level_index] if level_index < len(level_names) else f"Level{level_index}",
                        "level_value": level_value
                    })
    
    return matching_songs



async def random_song(range_str: Optional[str], user_id: str, message_id: int) -> BotResponse:
    """随机选择一首乐曲并显示信息。"""
    logger.debug(f"随机乐曲查询: range={range_str}, user={user_id}")

    # 解析难度范围
    if range_str:
        difficulty_range = parse_difficulty_range(range_str)
        if difficulty_range is None:
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
        min_ds, max_ds = difficulty_range
    else:
        min_ds, max_ds = 0.0, float("inf")

    # 获取符合条件的乐曲
    matching_songs = get_songs_by_difficulty_range(min_ds, max_ds)

    if not matching_songs:
        if range_str:
            return BotResponse(
                text=f"未找到难度范围在 {range_str} 的乐曲",
                reply_to=message_id,
            )
        else:
            return BotResponse(
                text="曲库数据为空，请联系管理员更新数据",
                reply_to=message_id,
            )

    # 随机选择一首
    selected = random.choice(matching_songs)
    song_data = selected["song_data"]
    song_id = song_data["id"]

    logger.info(
        f"随机到乐曲: [{song_id}] {song_data.get('title', '')} "
        f"[{selected['song_type'].upper()} {selected['level_name']}] "
        f"Level Value: {selected['level_value']}"
    )

    # 获取并更新收藏信息
    collections = await fetch_and_update_collections(song_id)
    if collections:
        song_data["collections"] = collections
        logger.debug(f"已加载 {len(collections)} 项收藏信息")

    # 渲染图片
    try:
        song_info_img = await mai_bg_draw.render_song_info_img(song_data)

        level_display = selected["difficulty"].get("level", str(selected["level_value"]))
        range_text = f" (定数: {selected['level_value']})" if range_str else ""
        description = (
            f"\n🎲 随机到的乐曲{range_text}：\n"
            f"[{song_id}] {song_data.get('title', '')}\n"
            f"[{selected['song_type'].upper()} {selected['level_name']} {level_display}]"
        )

        return BotResponse(text=description, image=song_info_img, reply_to=message_id)
    except Exception as e:
        traceback.print_exc()
        logger.error(f"渲染乐曲信息图片失败: {e}")
        return BotResponse(text=f"渲染图片失败: {str(e)}", reply_to=message_id)
