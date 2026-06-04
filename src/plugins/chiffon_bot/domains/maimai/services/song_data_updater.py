"""Maimai-specific song update helpers.

Cross-game catalog refresh lives in ``shared.song_data_updater``.  This module
keeps maimai-only collection fetching and a compatibility export for
``refresh_song_data``.
"""

from __future__ import annotations

import traceback

import aiohttp
from nonebot import logger

from ....infra.http import http_client
from ....integrations.lxns.constants import maimai_song_collections_url
from ....shared.song_data_updater import refresh_song_data


async def fetch_song_collection(song_id: int) -> list:
    """Fetch one maimai song's collection metadata."""

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


__all__ = ["fetch_song_collection", "refresh_song_data"]
