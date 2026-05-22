from nonebot import logger

from ....integrations.lxns.plugin_data import plugin_data
from .song_data_updater import fetch_song_collection
from .song_data_sync import sync_song_collections


async def fetch_and_update_collections(song_id: int) -> list:
    """获取并更新单个乐曲的收藏信息。

    Args:
        song_id: 乐曲 ID

    Returns:
        收藏信息列表
    """
    if hasattr(plugin_data, 'mai_collections_data'):
        cached = plugin_data.mai_collections_data.get(song_id)
        if cached:
            logger.debug(f"从缓存获取乐曲 {song_id} 的收藏信息")
            return cached

    collections = await fetch_song_collection(song_id)

    if collections:
        if not hasattr(plugin_data, 'mai_collections_data'):
            plugin_data.mai_collections_data = {}
        plugin_data.mai_collections_data[song_id] = collections
        await sync_song_collections(song_id, collections)

    return collections
