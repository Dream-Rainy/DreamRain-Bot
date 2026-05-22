"""乐曲数据更新服务 — 编排各游戏的数据拉取、同步与缓存刷新。

具体拉取逻辑已拆分至：
- ``maimai_data_fetcher.py`` — maimai (dxrating + LXNS + 柚子查 + Map XML)
- ``chunithm/services/chunithm_data_fetcher.py`` — chunithm (arcade-songs + LXNS)
"""

from __future__ import annotations

import traceback
import asyncio

import aiohttp
from nonebot import logger

from ....infra.http import http_client
from ....integrations.lxns.constants import maimai_song_collections_url
from ....integrations.lxns.plugin_data import plugin_data
from ...chunithm.views.chuni_bg_draw import clear_chuni_song_info_img_cache
from ..views import clear_all_img_cache
from .song_data_sync import (
    sync_mai_song_data,
    load_mai_song_index_from_db,
    sync_chuni_song_data,
    load_chuni_song_index_from_db,
)
from .maimai_data_fetcher import fetch_maimai_raw_data
from ...chunithm.services.chunithm_data_fetcher import fetch_chunithm_raw_data


_refresh_task: asyncio.Task[None] | None = None


async def fetch_song_collection(song_id: int) -> list:
    """获取单个乐曲的收藏信息（奖杯、称号等）。

    Args:
        song_id: 乐曲 ID

    Returns:
        收藏信息列表 [{type, id, name, color, genre}]
    """
    logger.debug(f"获取乐曲 {song_id} 的收藏信息")
    try:
        result = await http_client.get_json(maimai_song_collections_url(song_id))
        return result if isinstance(result, list) else []
    except aiohttp.ClientResponseError as e:
        traceback.print_exc()
        logger.warning(f"获取乐曲 {song_id} 的收藏信息失败 ({e.status}): {e}")
        return []
    except Exception as e:
        traceback.print_exc()
        logger.warning(f"获取乐曲 {song_id} 的收藏信息失败: {e}")
        return []


async def _sync_maimai_from_remote() -> bool:
    """从远端同步 maimai 曲库，成功后再刷新内存缓存。"""
    try:
        logger.info("=" * 50)
        logger.info("开始后台更新 maimai 乐曲数据")
        logger.info("=" * 50)

        maimai_data = await fetch_maimai_raw_data()
        await sync_mai_song_data(maimai_data)
        plugin_data.mai_song_index = {song_id: song.title for song_id, song in maimai_data.items()}
        plugin_data.mai_song_data = {}
        clear_all_img_cache()
        logger.info("maimai 乐曲数据后台更新完成")
        return True
    except Exception as e:
        traceback.print_exc()
        logger.error(f"后台更新 maimai 乐曲数据失败，继续使用本地数据: {e}")
        return False


async def _sync_chunithm_from_remote() -> bool:
    """从远端同步 chunithm 曲库，成功后再刷新内存缓存。"""
    try:
        logger.info("=" * 50)
        logger.info("开始后台更新 chunithm 乐曲数据")
        logger.info("=" * 50)

        chuni_data = await fetch_chunithm_raw_data()
        await sync_chuni_song_data(chuni_data)
        plugin_data.chuni_song_index = {song_id: song.title for song_id, song in chuni_data.items()}
        plugin_data.chuni_song_data = {}
        clear_chuni_song_info_img_cache()
        logger.info("chunithm 乐曲数据后台更新完成")
        return True
    except Exception as e:
        traceback.print_exc()
        logger.error(f"后台更新 chunithm 乐曲数据失败，继续使用本地数据: {e}")
        return False


async def _sync_song_data_from_remote() -> None:
    """后台同步所有曲库数据。"""
    maimai_ok, chuni_ok = await asyncio.gather(
        _sync_maimai_from_remote(),
        _sync_chunithm_from_remote(),
    )
    if maimai_ok and chuni_ok:
        logger.info("全部乐曲数据后台同步完成")
    elif maimai_ok or chuni_ok:
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
    """启动后台刷新任务。返回 True 表示本次创建了新任务。"""
    global _refresh_task
    if _refresh_task and not _refresh_task.done():
        return False

    _refresh_task = asyncio.create_task(_sync_song_data_from_remote())
    _refresh_task.add_done_callback(_on_refresh_task_done)
    return True


async def _load_song_data_from_db() -> tuple[bool, str]:
    """优先从本地数据库加载轻量曲库索引到内存。"""
    maimai_index, chuni_index = await asyncio.gather(
        load_mai_song_index_from_db(),
        load_chuni_song_index_from_db(),
    )

    loaded_games: list[str] = []
    plugin_data.mai_song_data = {}
    plugin_data.chuni_song_data = {}
    if maimai_index:
        plugin_data.mai_song_index = maimai_index
        loaded_games.append(f"maimai {len(maimai_index)} 首")
    if chuni_index:
        plugin_data.chuni_song_index = chuni_index
        loaded_games.append(f"chunithm {len(chuni_index)} 首")

    if loaded_games:
        return True, "已加载本地数据库曲库索引：" + "，".join(loaded_games)
    return False, "本地数据库暂无可用曲库索引"


async def refresh_song_data() -> tuple[bool, str]:
    """本地优先刷新所有乐曲数据（maimai + chunithm）。

    调用时先从数据库加载历史索引并立即返回，然后在后台尝试同步远端数据。
    远端同步只有在 fetch 与数据库写入都成功后，才会刷新轻量索引。

    Returns:
        (本地是否可用, 更新信息消息)
    """
    local_available, local_msg = await _load_song_data_from_db()
    started = _start_background_refresh()

    if started:
        return local_available, f"{local_msg}；已启动后台同步"
    return local_available, f"{local_msg}；后台同步已在进行中"
