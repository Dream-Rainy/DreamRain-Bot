"""Cross-game song catalog refresh orchestration."""

from __future__ import annotations

import asyncio
import traceback

from nonebot import logger

from .game.adapter import DomainAdapter
from .generic_sync import generic_sync_to_db
from ..integrations.lxns.plugin_data import plugin_data

_refresh_task: asyncio.Task[None] | None = None


def _domain_adapters() -> list[DomainAdapter]:
    from ..domains.maimai.maimai_adapter import get_maimai_adapter
    from ..domains.chunithm.chunithm_adapter import get_chunithm_adapter

    return [get_maimai_adapter(), get_chunithm_adapter()]


def _song_index_attr(adapter: DomainAdapter) -> str:
    return str(getattr(adapter, "song_index_attr"))


def _song_store_attr(adapter: DomainAdapter) -> str:
    return str(getattr(adapter, "song_store_attr"))


async def _sync_adapter_from_remote(adapter: DomainAdapter) -> bool:
    """Sync one game from remote sources, then refresh its lightweight index."""

    gc = adapter.game_code
    try:
        logger.info("=" * 50)
        logger.info(f"开始后台更新 {gc} 乐曲数据")
        logger.info("=" * 50)

        song_data = await adapter.fetch_raw_data()
        await generic_sync_to_db(adapter, song_data)
        setattr(
            plugin_data,
            _song_index_attr(adapter),
            {song_id: song.title for song_id, song in song_data.items()},
        )
        setattr(plugin_data, _song_store_attr(adapter), {})
        adapter.clear_image_cache()
        logger.info(f"{gc} 乐曲数据后台更新完成")
        return True
    except Exception as e:
        traceback.print_exc()
        logger.error(f"后台更新 {gc} 乐曲数据失败，继续使用本地数据: {e}")
        return False


async def _sync_song_data_from_remote() -> None:
    """Sync all registered game catalogs in the background."""

    adapters = _domain_adapters()
    results = await asyncio.gather(*(_sync_adapter_from_remote(adapter) for adapter in adapters))

    ok_count = sum(1 for ok in results if ok)
    if ok_count == len(results):
        logger.info("全部乐曲数据后台同步完成")
    elif ok_count:
        logger.warning("乐曲数据后台同步部分完成，失败的游戏继续使用本地数据")
    else:
        logger.warning("乐曲数据后台同步全部失败，继续使用本地数据")


def _on_refresh_task_done(task: asyncio.Task[None]) -> None:
    global _refresh_task
    _refresh_task = None
    try:
        task.result()
    except asyncio.CancelledError:
        logger.warning("乐曲数据后台同步任务已取消")
    except Exception as e:
        logger.error(f"乐曲数据后台同步任务异常结束: {e}")


def _start_background_refresh() -> bool:
    """Start the background refresh task if it is not already running."""

    global _refresh_task
    if _refresh_task and not _refresh_task.done():
        return False

    _refresh_task = asyncio.create_task(_sync_song_data_from_remote())
    _refresh_task.add_done_callback(_on_refresh_task_done)
    return True


async def _load_song_data_from_db() -> tuple[bool, str]:
    """Load lightweight song indexes from local DB first."""

    adapters = _domain_adapters()
    indexes = await asyncio.gather(*(adapter.load_song_index_from_db() for adapter in adapters))

    loaded_games: list[str] = []
    for adapter, index in zip(adapters, indexes, strict=True):
        setattr(plugin_data, _song_store_attr(adapter), {})
        if index:
            setattr(plugin_data, _song_index_attr(adapter), index)
            loaded_games.append(f"{adapter.display_name} {len(index)} 首")

    if loaded_games:
        return True, "已加载本地数据库曲库索引：" + "，".join(loaded_games)
    return False, "本地数据库暂无可用曲库索引"


async def refresh_song_data() -> tuple[bool, str]:
    """Load local song indexes and start remote background refresh."""

    local_available, local_msg = await _load_song_data_from_db()
    started = _start_background_refresh()

    if started:
        return local_available, f"{local_msg}；已启动后台同步"
    return local_available, f"{local_msg}；后台同步已在进行中"
