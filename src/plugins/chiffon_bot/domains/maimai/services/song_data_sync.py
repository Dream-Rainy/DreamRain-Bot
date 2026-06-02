"""乐曲数据同步服务：将 LXNS/柚子查数据同步到本地数据库。

启动时调用，用于初始化/更新本地曲库缓存。
"""

import traceback
from nonebot import logger

from ....infra.db.models import (
    MaiSong,
    MaiSongAlias,
    MaiMap,
    MaiMapTreasure,
    ChuniSong,
    ChuniSongAlias,
)
from ..schemas import MaiSongData, MapData, MapTreasureData
from ...chunithm.schemas import ChuniSongData
from ...chunithm.services.chunithm_data_fetcher import build_chuni_jacket_image_name

_DEFAULT_MAI_JACKET_IMAGE_NAME = "jacket/UI_Jacket_000000.png"


def _fallback_mai_image_name(song_id: int) -> str:
    if 0 < song_id < 10000000:
        jacket_id = song_id % 10000 if song_id > 10000 else song_id
        return f"jacket/UI_Jacket_{jacket_id:0>6}.png"
    return _DEFAULT_MAI_JACKET_IMAGE_NAME


def _mai_song_from_db_row(row: MaiSong, aliases: list[str]) -> MaiSongData:
    song_dict = {
        "id": row.id,
        "title": row.title,
        "artist": row.artist,
        "category": row.category,
        "bpm": row.bpm,
        "version": row.version,
        "rights": row.rights,
        "mai_map": row.mai_map,
        "releaseDate": row.release_date,
        "image_name": row.image_name or _fallback_mai_image_name(row.id),
        "isNew": row.is_new,
        "isLocked": row.is_locked,
        "comment": row.comment,
        "difficulties": row.difficulties or {},
        "collections": row.collections or [],
        "aliases": aliases,
    }
    return MaiSongData.from_dict(song_dict)


def _chuni_song_from_db_row(row: ChuniSong, aliases: list[str]) -> ChuniSongData:
    return ChuniSongData.model_validate({
        "id": row.id,
        "title": row.title,
        "artist": row.artist or "",
        "genre": row.genre or "",
        "bpm": row.bpm or 0,
        "version": row.version,
        "rights": row.rights,
        "difficulties": row.difficulties or {},
        "image_name": row.image_name or build_chuni_jacket_image_name(row.id),
        "release_date": "",
        "is_new": False,
        "is_locked": False,
        "comment": "",
        "aliases": aliases,
    })


async def sync_mai_song_data(
    song_data: dict[int, MaiSongData],
) -> None:
    """同步 maimai 乐曲数据到数据库。
    
    Args:
        song_data: {song_id: MaiSongData} 乐曲数据（合并 dxrating 和 LXNS，包含别名）
    """
    logger.info(f"开始同步 maimai 乐曲数据到数据库，共 {len(song_data)} 首")

    # 清理无法确定 ID 而分配的临时 song_id（从 10000000 起）
    # 这些记录在数据源顺序/内容变化时会残留，导致同一首歌出现多条脏数据
    try:
        deleted_aliases = await MaiSongAlias.filter(song_id__gte=10000000).delete()
        deleted_songs = await MaiSong.filter(id__gte=10000000).delete()
        if deleted_aliases or deleted_songs:
            logger.info(
                f"已清理历史临时乐曲数据：删除 {deleted_songs} 首临时歌曲，{deleted_aliases} 条别名"
            )
    except Exception as e:
        logger.warning(f"清理历史临时乐曲数据失败，将继续尝试同步: {e}")
    
    synced_count = 0
    alias_count = 0
    
    for song_id, song_model in song_data.items():
        # 转为字典便于访问
        song = song_model.to_dict()
        
        # 更新或创建乐曲主记录（不包含收藏信息）
        mai_song, created = await MaiSong.update_or_create(
            id=song_id,
            defaults={
                "title": song.get("title", ""),
                "artist": song.get("artist"),
                "category": song.get("category"),
                "bpm": song.get("bpm"),
                "version": song.get("version"),
                "rights": song.get("rights"),
                "mai_map": song.get("mai_map"),  # 添加地图信息
                "release_date": song.get("releaseDate"),
                "image_name": song.get("image_name") or "",
                "is_new": song.get("isNew", False),
                "is_locked": song.get("isLocked", False),
                "comment": song.get("comment"),
                "difficulties": song.get("difficulties", []),
            }
        )
        synced_count += 1
        
        # 处理别名（直接从song对象的aliases字段获取）
        aliases_to_sync: list[str] = song_model.aliases or []
        
        # 去重并保持顺序
        seen = set()
        unique_aliases = []
        for alias in aliases_to_sync:
            alias_lower = alias.lower()
            if alias_lower not in seen and alias:
                seen.add(alias_lower)
                unique_aliases.append(alias)
        
        # 获取现有别名
        existing_aliases = await MaiSongAlias.filter(song_id=song_id).values_list("alias", flat=True)
        existing_set = set(str(a).lower() for a in existing_aliases)
        
        # 添加新别名
        for priority, alias in enumerate(unique_aliases):
            if alias.lower() not in existing_set:
                await MaiSongAlias.create(
                    song=mai_song,
                    alias=alias,
                    priority=priority,  # 越小优先级越高
                )
                alias_count += 1
    
    logger.info(f"maimai 乐曲数据同步完成：{synced_count} 首乐曲，新增 {alias_count} 条别名")
    # 同步后失效查询层别名缓存，确保后续查询看到最新数据
    try:
        from .song_query import invalidate_alias_cache
        invalidate_alias_cache()
    except Exception as e:
        logger.warning(f"失效别名缓存失败（可忽略，下次 TTL 到期会自动刷新）: {e}")


async def load_mai_song_data_from_db() -> dict[int, MaiSongData]:
    """从数据库加载 maimai 乐曲数据到内存结构。
    
    Returns:
        {song_id: MaiSongData} 乐曲数据字典
    """
    logger.info("从数据库加载 maimai 乐曲历史数据...")
    try:
        songs = await MaiSong.all()
        if not songs:
            logger.warning("数据库中没有 maimai 乐曲数据")
            return {}

        song_ids = [song.id for song in songs]
        aliases_by_song_id: dict[int, list[str]] = {song_id: [] for song_id in song_ids}

        alias_rows = await MaiSongAlias.filter(song_id__in=song_ids).order_by(
            "song_id", "priority", "id"
        ).values("song_id", "alias")
        for row in alias_rows:
            song_id = row.get("song_id")
            alias = row.get("alias")
            if song_id is not None and alias:
                aliases_by_song_id.setdefault(song_id, []).append(alias)

        merged_songs: dict[int, MaiSongData] = {}
        for song in songs:
            merged_songs[song.id] = _mai_song_from_db_row(
                song,
                aliases_by_song_id.get(song.id, []),
            )

        logger.info(f"从数据库加载完成：共 {len(merged_songs)} 首歌曲")
        return merged_songs
    except Exception as e:
        logger.error(f"从数据库加载 maimai 乐曲数据失败: {e}")
        traceback.print_exc()
        return {}


async def load_mai_song_index_from_db() -> dict[int, str]:
    """从数据库加载 maimai 轻量曲库索引。"""
    try:
        rows = await MaiSong.all().values("id", "title")
        return {
            int(row["id"]): str(row.get("title") or "")
            for row in rows
            if row.get("id") is not None
        }
    except Exception as e:
        logger.error(f"从数据库加载 maimai 乐曲索引失败: {e}")
        traceback.print_exc()
        return {}


async def load_mai_song_by_id_from_db(song_id: int) -> MaiSongData | None:
    """从数据库按 ID 加载单首 maimai 乐曲完整数据。"""
    try:
        song = await MaiSong.get_or_none(id=song_id)
        if song is None:
            return None
        aliases = await MaiSongAlias.filter(song_id=song_id).order_by(
            "priority", "id"
        ).values_list("alias", flat=True)
        return _mai_song_from_db_row(song, [str(a) for a in aliases if a])
    except Exception as e:
        logger.error(f"从数据库加载 maimai 乐曲 {song_id} 失败: {e}")
        traceback.print_exc()
        return None


async def sync_chuni_song_data(song_data: dict[int, ChuniSongData]) -> None:
    """同步 chunithm 乐曲数据到数据库（合并 arcade-songs + LXNS 后的内存结构）。"""

    logger.info(f"开始同步 chunithm 乐曲数据到数据库，共 {len(song_data)} 首")

    try:
        deleted_aliases = await ChuniSongAlias.filter(song_id__gte=100000).delete()
        deleted_songs = await ChuniSong.filter(id__gte=100000).delete()
        if deleted_aliases or deleted_songs:
            logger.info(
                f"已清理 chunithm 历史临时乐曲数据：删除 {deleted_songs} 首临时歌曲，"
                f"{deleted_aliases} 条别名"
            )
    except Exception as e:
        logger.warning(f"清理 chunithm 历史临时乐曲数据失败，将继续尝试同步: {e}")

    synced_count = 0
    for song_id, song in song_data.items():
        genre = song.genre
        version_int = song.version

        chuni_song, _ = await ChuniSong.update_or_create(
            id=song_id,
            defaults={
                "title": song.title or "",
                "artist": song.artist,
                "genre": (genre[:64] if isinstance(genre, str) and genre else None),
                "bpm": song.bpm,
                "version": version_int,
                "rights": song.rights,
                "image_name": song.image_name or "",
                "difficulties": {
                    t: [s.model_dump(mode="json", by_alias=True, exclude_none=True) for s in sheets]
                    for t, sheets in (song.difficulties or {}).items()
                },
            },
        )
        synced_count += 1

        # 同步别名
        aliases_to_sync: list[str] = song.aliases or []
        seen: set[str] = set()
        unique_aliases: list[str] = []
        for alias in aliases_to_sync:
            if alias and alias.lower() not in seen:
                seen.add(alias.lower())
                unique_aliases.append(alias)

        if unique_aliases:
            existing_aliases = set(
                str(a).lower()
                for a in await ChuniSongAlias.filter(song_id=song_id).values_list("alias", flat=True)
            )
            for priority, alias in enumerate(unique_aliases):
                if alias.lower() not in existing_aliases:
                    await ChuniSongAlias.create(
                        song=chuni_song,
                        alias=alias,
                        priority=priority,
                    )

    logger.info(f"chunithm 乐曲数据同步完成：{synced_count} 首乐曲")
    try:
        from .song_query import invalidate_alias_cache

        invalidate_alias_cache()
    except Exception as e:
        logger.warning(f"失效别名缓存失败（chunithm，可忽略）: {e}")


async def load_chuni_song_data_from_db() -> dict[int, ChuniSongData]:
    """从数据库加载 chunithm 乐曲数据到内存。"""

    logger.info("从数据库加载 chunithm 乐曲历史数据...")
    try:
        songs = await ChuniSong.all()
        if not songs:
            logger.warning("数据库中没有 chunithm 乐曲数据")
            return {}

        song_ids = [song.id for song in songs]

        aliases_by_song_id: dict[int, list[str]] = {sid: [] for sid in song_ids}
        alias_rows = await ChuniSongAlias.filter(song_id__in=song_ids).order_by(
            "song_id", "priority", "id"
        ).values("song_id", "alias")
        for row in alias_rows:
            sid = row.get("song_id")
            alias = row.get("alias")
            if sid is not None and alias:
                aliases_by_song_id.setdefault(sid, []).append(str(alias))

        merged: dict[int, ChuniSongData] = {}
        for song in songs:
            merged[song.id] = _chuni_song_from_db_row(
                song,
                aliases_by_song_id.get(song.id, []),
            )

        logger.info(f"chunithm 从数据库加载完成：共 {len(merged)} 首歌曲")
        return merged
    except Exception as e:
        logger.error(f"从数据库加载 chunithm 乐曲数据失败: {e}")
        traceback.print_exc()
        return {}


async def load_chuni_song_index_from_db() -> dict[int, str]:
    """从数据库加载 chunithm 轻量曲库索引。"""
    try:
        rows = await ChuniSong.all().values("id", "title")
        return {
            int(row["id"]): str(row.get("title") or "")
            for row in rows
            if row.get("id") is not None
        }
    except Exception as e:
        logger.error(f"从数据库加载 chunithm 乐曲索引失败: {e}")
        traceback.print_exc()
        return {}


async def load_chuni_song_by_id_from_db(song_id: int) -> ChuniSongData | None:
    """从数据库按 ID 加载单首 chunithm 乐曲完整数据。"""
    try:
        song = await ChuniSong.get_or_none(id=song_id)
        if song is None:
            return None
        aliases = await ChuniSongAlias.filter(song_id=song_id).order_by(
            "priority", "id"
        ).values_list("alias", flat=True)
        return _chuni_song_from_db_row(song, [str(a) for a in aliases if a])
    except Exception as e:
        logger.error(f"从数据库加载 chunithm 乐曲 {song_id} 失败: {e}")
        traceback.print_exc()
        return None


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
