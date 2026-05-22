"""通用数据同步器 — 替代各 domain 重复的 sync/load 逻辑。

通过 ``DomainAdapter`` 获取游戏差异（DB 模型、字段映射等），
实现与游戏无关的同步 / 加载流程。
"""

from __future__ import annotations

import traceback

from nonebot import logger

from .domain_adapter import DomainAdapter
from .song_data import SongData


async def generic_sync_to_db(
    adapter: DomainAdapter,
    song_data: dict[int, SongData],
) -> None:
    """将曲库数据同步到数据库。

    流程：清理临时数据 → 遍历 update_or_create → 别名去重 → 失效缓存。
    """
    gc = adapter.game_code
    logger.info(f"[{gc}] 开始同步乐曲数据到数据库，共 {len(song_data)} 首")

    SongModel = adapter.get_db_song_model()
    AliasModel = adapter.get_db_alias_model()

    # 1. 清理临时 ID 脏数据
    threshold = adapter.temp_id_threshold
    try:
        deleted_aliases = await AliasModel.filter(song_id__gte=threshold).delete()
        deleted_songs = await SongModel.filter(id__gte=threshold).delete()
        if deleted_aliases or deleted_songs:
            logger.info(
                f"[{gc}] 已清理历史临时乐曲数据："
                f"删除 {deleted_songs} 首临时歌曲，{deleted_aliases} 条别名"
            )
    except Exception as e:
        logger.warning(f"[{gc}] 清理历史临时乐曲数据失败，将继续尝试同步: {e}")

    # 2. 遍历同步
    synced_count = 0
    alias_count = 0

    for song_id, song in song_data.items():
        defaults = adapter.song_to_db_defaults(song)

        db_song, _ = await SongModel.update_or_create(
            id=song_id,
            defaults=defaults,
        )
        synced_count += 1

        # 3. 别名去重 & 增量写入
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
                for a in await AliasModel.filter(song_id=song_id).values_list(
                    "alias", flat=True
                )
            )
            for priority, alias in enumerate(unique_aliases):
                if alias.lower() not in existing_aliases:
                    await AliasModel.create(
                        song=db_song,
                        alias=alias,
                        priority=priority,
                    )
                    alias_count += 1

    logger.info(f"[{gc}] 乐曲数据同步完成：{synced_count} 首乐曲，新增 {alias_count} 条别名")

    # 4. 失效查询层缓存
    try:
        from .search.song_query import invalidate_alias_cache

        invalidate_alias_cache(gc)
    except Exception as e:
        logger.warning(f"[{gc}] 失效别名缓存失败（可忽略，下次 TTL 到期会自动刷新）: {e}")


async def generic_load_from_db(
    adapter: DomainAdapter,
) -> dict[int, SongData]:
    """从数据库加载曲库数据到内存。

    Returns:
        {song_id: SongData 子类实例}，数据库为空时返回 {}。
    """
    gc = adapter.game_code
    logger.info(f"[{gc}] 从数据库加载乐曲历史数据...")

    try:
        SongModel = adapter.get_db_song_model()
        AliasModel = adapter.get_db_alias_model()

        songs = await SongModel.all()
        if not songs:
            logger.warning(f"[{gc}] 数据库中没有乐曲数据")
            return {}

        song_ids = [song.id for song in songs]

        # 加载别名
        aliases_by_song_id: dict[int, list[str]] = {sid: [] for sid in song_ids}
        alias_rows = (
            await AliasModel.filter(song_id__in=song_ids)
            .order_by("song_id", "priority", "id")
            .values("song_id", "alias")
        )
        for row in alias_rows:
            sid = row.get("song_id")
            alias = row.get("alias")
            if sid is not None and alias:
                aliases_by_song_id.setdefault(sid, []).append(str(alias))

        # 转换为 SongData 子类
        merged: dict[int, SongData] = {}
        for song in songs:
            merged[song.id] = adapter.song_from_db_row(
                song,
                aliases_by_song_id.get(song.id, []),
            )

        logger.info(f"[{gc}] 从数据库加载完成：共 {len(merged)} 首歌曲")
        return merged

    except Exception as e:
        logger.error(f"[{gc}] 从数据库加载乐曲数据失败: {e}")
        traceback.print_exc()
        return {}
