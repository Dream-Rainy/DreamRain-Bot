"""乐曲数据同步服务：将 LXNS/柚子查数据同步到本地数据库。

启动时调用，用于初始化/更新本地曲库缓存。
"""

import traceback
from nonebot import logger

from ....infra.db.models import (
    MaiMap,
    MaiMapTreasure,
)
from ..schemas import MaiSongData, MapData, MapTreasureData
from ....shared.generic_sync import generic_sync_to_db

async def sync_mai_song_data(
    song_data: dict[int, MaiSongData],
) -> None:
    """同步 maimai 乐曲数据到数据库。
    
    Args:
        song_data: {song_id: MaiSongData} 乐曲数据（合并 dxrating 和 LXNS，包含别名）
    """
    from ..maimai_adapter import get_maimai_adapter

    await generic_sync_to_db(get_maimai_adapter(), song_data)  # type: ignore[arg-type]


async def load_mai_song_data_from_db() -> dict[int, MaiSongData]:
    """从数据库加载 maimai 乐曲数据到内存结构。
    
    Returns:
        {song_id: MaiSongData} 乐曲数据字典
    """
    from ..maimai_adapter import get_maimai_adapter

    return await get_maimai_adapter().load_all_songs()  # type: ignore[return-value]


async def load_mai_song_index_from_db() -> dict[int, str]:
    """从数据库加载 maimai 轻量曲库索引。"""
    from ..maimai_adapter import get_maimai_adapter

    return await get_maimai_adapter().load_song_index_from_db()


async def load_mai_song_by_id_from_db(song_id: int) -> MaiSongData | None:
    """从数据库按 ID 加载单首 maimai 乐曲完整数据。"""
    from ..maimai_adapter import get_maimai_adapter

    return await get_maimai_adapter().get_song_by_id(song_id)  # type: ignore[return-value]


async def sync_song_collections(song_id: int, collections: list) -> None:
    """同步单个乐曲的收藏信息到数据库。
    
    Args:
        song_id: 乐曲 ID
        collections: 收藏信息列表 [{type, id, name, color, genre}]
    """
    logger.debug(f"同步乐曲 {song_id} 的收藏信息到数据库")
    try:
        await MaiSong.filter(id=song_id).update(collections=collections)
        logger.debug(f"成功同步乐曲 {song_id} 的 {len(collections)} 项收藏信息")
    except Exception as e:
        traceback.print_exc()
        logger.warning(f"同步乐曲 {song_id} 收藏信息失败: {e}")


async def sync_mai_map_data(map_data: dict[int, MapData]) -> None:
    """同步 maimai 地图数据到数据库。
    
    Args:
        map_data: {map_id: MapData} 地图数据字典
    """
    logger.info(f"开始同步 maimai 地图数据到数据库，共 {len(map_data)} 个地图")
    
    synced_count = 0
    
    for map_id, map_model in map_data.items():
        try:
            # 转为字典便于访问
            map_dict = {
                "data_name": map_model.data_name,
                "map_name": map_model.map_name,
                "is_collabo": map_model.is_collabo,
                "is_infinity": map_model.is_infinity,
                "island_id": map_model.island_id,
                "island_name": map_model.island_name,
                "color_id": map_model.color_id,
                "color_name": map_model.color_name,
                "bonus_music_id": map_model.bonus_music_id,
                "bonus_music_name": map_model.bonus_music_name,
                "bonus_music_magnification": map_model.bonus_music_magnification,
                "open_event_id": map_model.open_event_id,
                "open_event_name": map_model.open_event_name,
                "net_open_name_id": map_model.net_open_name_id,
                "net_open_name": map_model.net_open_name,
                # 将treasures序列化为JSON
                "treasures": [t.model_dump(by_alias=True) for t in map_model.treasures],
            }
            
            # 更新或创建地图记录
            await MaiMap.update_or_create(
                id=map_id,
                defaults=map_dict
            )
            synced_count += 1
            
        except Exception as e:
            logger.warning(f"同步地图 {map_id} 失败: {e}")
            traceback.print_exc()
    
    logger.info(f"maimai 地图数据同步完成：{synced_count} 个地图")


async def sync_mai_map_treasure_data(treasure_data: dict[int, MapTreasureData]) -> None:
    """同步 maimai 地图奖励数据到数据库。
    
    Args:
        treasure_data: {treasure_id: MapTreasureData} 奖励数据字典
    """
    logger.info(f"开始同步 maimai 地图奖励数据到数据库，共 {len(treasure_data)} 个奖励")
    
    synced_count = 0
    
    for treasure_id, treasure_model in treasure_data.items():
        try:
            # 更新或创建奖励记录
            await MaiMapTreasure.update_or_create(
                id=treasure_id,
                defaults={
                    "data_name": treasure_model.data_name,
                    "treasure_name": treasure_model.treasure_name,
                    "treasure_type": treasure_model.treasure_type,
                    "character_id": treasure_model.character_id,
                    "character_name": treasure_model.character_name,
                    "music_id": treasure_model.music_id,
                    "music_name": treasure_model.music_name,
                    "numeric": treasure_model.numeric,
                    "name_plate_id": treasure_model.name_plate_id,
                    "name_plate_name": treasure_model.name_plate_name,
                    "frame_id": treasure_model.frame_id,
                    "frame_name": treasure_model.frame_name,
                    "title_id": treasure_model.title_id,
                    "title_name": treasure_model.title_name,
                    "icon_id": treasure_model.icon_id,
                    "icon_name": treasure_model.icon_name,
                    "challenge_id": treasure_model.challenge_id,
                    "challenge_name": treasure_model.challenge_name,
                    "gate_id": treasure_model.gate_id,
                    "gate_name": treasure_model.gate_name,
                    "key_id": treasure_model.key_id,
                    "key_name": treasure_model.key_name,
                }
            )
            synced_count += 1
            
        except Exception as e:
            logger.warning(f"同步奖励 {treasure_id} 失败: {e}")
            traceback.print_exc()
    
    logger.info(f"maimai 地图奖励数据同步完成：{synced_count} 个奖励")
