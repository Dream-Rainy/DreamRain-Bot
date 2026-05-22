"""乐曲查询示例：展示如何使用 song_query 服务。

此文件仅作为参考，实际指令交互由你自行实现。
"""

# 在你的指令处理器中，可以这样使用：

from src.plugins.chiffon_bot.domains.maimai.services import (
    search_song,
    SongQueryResult,
    MatchType,
    get_song_with_difficulty,
)
from src.plugins.chiffon_bot.domains.maimai.services.song_data_updater import (
    fetch_song_collection,
)
from src.plugins.chiffon_bot.domains.maimai.services.song_data_sync import (
    sync_song_collections,
)
from src.plugins.chiffon_bot.integrations.lxns.plugin_data import plugin_data


async def example_search_handler(user_input: str):
    """示例：搜索乐曲
    
    支持的输入格式：
    - 数字 ID：如 "146"
    - 精确标题：如 "39"
    - 别名：如 "标39"、"初音未来"
    - 模糊搜索：如 "初音"、"miku"
    """
    results = await search_song(user_input)
    
    if not results:
        return "未找到匹配的乐曲"
    
    # 为所有查询结果获取 collections 信息（按需）
    for result in results:
        await fetch_and_update_collections(result.song_id)
    
    if len(results) == 1:
        # 单一结果
        result = results[0]
        return format_single_result(result)
    else:
        # 多个结果
        return format_multiple_results(results)


async def fetch_and_update_collections(song_id: int) -> list:
    """获取并更新单个乐曲的收藏信息
    
    Args:
        song_id: 乐曲 ID
        
    Returns:
        收藏信息列表
    """
    # 从缓存中获取
    if hasattr(plugin_data, 'mai_collections_data'):
        cached = plugin_data.mai_collections_data.get(song_id)
        if cached:
            return cached
    
    # 从 API 获取
    collections = await fetch_song_collection(song_id)
    
    if collections:
        # 更新到内存缓存
        if not hasattr(plugin_data, 'mai_collections_data'):
            plugin_data.mai_collections_data = {}
        plugin_data.mai_collections_data[song_id] = collections
        
        # 更新到数据库
        await sync_song_collections(song_id, collections)
    
    return collections


def format_single_result(result: SongQueryResult) -> str:
    """格式化单个结果"""
    song = result.song_data
    match_info = f"匹配方式: {result.match_type.value}, 匹配度: {result.match_score:.1f}%"
    
    return f"""
🎵 {song.title}
━━━━━━━━━━━━━━━━
🆔 ID: {result.song_id}
🎤 艺术家: {song.artist if hasattr(song, 'artist') else '未知'}
🏷️ 分类: {song.category if hasattr(song, 'category') else '未知'}
🎹 BPM: {song.bpm if hasattr(song, 'bpm') else '未知'}

{match_info}
"""


def format_multiple_results(results: list[SongQueryResult]) -> str:
    """格式化多个结果"""
    lines = ["🔍 找到多个匹配结果：\n"]
    
    for i, result in enumerate(results, 1):
        match_emoji = {
            MatchType.EXACT_ID: "🎯",
            MatchType.EXACT_TITLE: "✅",
            MatchType.EXACT_ALIAS: "✅",
            MatchType.FUZZY_TITLE: "🔸",
            MatchType.FUZZY_ALIAS: "🔸",
        }.get(result.match_type, "•")
        
        lines.append(
            f"{match_emoji} [{result.song_id}] {result.title} "
            f"({result.match_score:.0f}% via {result.matched_text})"
        )
    
    lines.append("\n请指定更精确的关键词或使用 ID 查询")
    return "\n".join(lines)


async def example_get_collections_info(song_id: int):
    """示例：获取乐曲的收藏信息（奖杯、称号等）
    
    Args:
        song_id: 乐曲 ID
    """
    collections = await fetch_and_update_collections(song_id)
    
    if not collections:
        return "该乐曲暂无收藏信息"
    
    lines = ["🏆 收藏信息：\n"]
    
    for item in collections:
        item_type = item.get('type', '未知')
        item_name = item.get('name', '未知')
        item_genre = item.get('genre', '')
        
        type_emoji = {
            'trophy': '🏆',
            'nameplate': '🎫',
            'frame': '🖼️',
        }.get(item_type, '📦')
        
        if item_genre:
            lines.append(f"{type_emoji} {item_name} ({item_genre})")
        else:
            lines.append(f"{type_emoji} {item_name}")
    
    return "\n".join(lines)


async def example_get_chart_info(song_id: int, chart_type: str = "standard", level_index: int = 3):
    """示例：获取指定难度的谱面信息
    
    Args:
        song_id: 乐曲 ID
        chart_type: "standard" 或 "dx"
        level_index: 0=Basic, 1=Advanced, 2=Expert, 3=Master, 4=Re:Master
    """
    song = await get_song_with_difficulty(song_id, chart_type, level_index)
    
    if not song:
        return "未找到乐曲"
    
    difficulty = song.get("target_difficulty")
    if not difficulty:
        return f"该乐曲没有 {chart_type.upper()} 谱面的难度 {level_index}"
    
    notes = difficulty.get("notes", {})
    return f"""
🎵 {song['title']} [{chart_type.upper()}]
━━━━━━━━━━━━━━━━
⭐ 难度: {difficulty.get('level', '?')} ({difficulty.get('level_value', '?')})
✏️ 谱师: {difficulty.get('note_designer', '-')}

📊 物量统计:
  Total: {notes.get('total', 0)}
  Tap: {notes.get('tap', 0)}
  Hold: {notes.get('hold', 0)}
  Slide: {notes.get('slide', 0)}
  Touch: {notes.get('touch', 0)}
  Break: {notes.get('break', 0)}
"""
