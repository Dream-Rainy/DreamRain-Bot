"""CHUNITHM DomainAdapter — 完整实现。"""

from __future__ import annotations

from typing import Any

from ...infra.db.models import ChuniSong, ChuniSongAlias
from ...shared.domain_adapter import DomainAdapter
from ...shared.song_data import SongData
from ..maimai.services.song_query import ChunithmSongQueryAdapter
from ..chunithm.schemas import ChuniSongData
from ..chunithm.views.chuni_bg_draw import (
    render_chuni_song_info_img as _render_img,
    clear_chuni_song_info_img_cache as _clear_cache,
)
from ..chunithm.services.chunithm_data_fetcher import fetch_chunithm_raw_data


class ChunithmDomainAdapter(ChunithmSongQueryAdapter, DomainAdapter):
    """CHUNITHM 域完整适配器。"""

    # ── 游戏常量 ──
    display_name = "CHUNITHM"
    level_names = ["BASIC", "ADVANCED", "EXPERT", "MASTER", "ULTIMA"]
    difficulty_types = ["standard", "ultima"]

    # ── 数据同步 ──
    temp_id_threshold = 100000

    def get_db_song_model(self) -> type:
        return ChuniSong

    def get_db_alias_model(self) -> type:
        return ChuniSongAlias

    def song_to_db_defaults(self, song: SongData) -> dict[str, Any]:
        genre = getattr(song, "genre", "") or ""
        diffs = getattr(song, "difficulties", None) or {}
        return {
            "title": song.title or "",
            "artist": getattr(song, "artist", None),
            "genre": (genre[:64] if isinstance(genre, str) and genre else None),
            "bpm": getattr(song, "bpm", None),
            "version": getattr(song, "version", None),
            "rights": getattr(song, "rights", None),
            "difficulties": {
                t: [s.model_dump(mode="json", by_alias=True, exclude_none=True) for s in sheets]
                for t, sheets in diffs.items()
            },
        }

    def song_from_db_row(self, row: Any, aliases: list[str]) -> SongData:
        return ChuniSongData.model_validate({
            "id": row.id,
            "title": row.title,
            "artist": row.artist or "",
            "genre": row.genre or "",
            "bpm": row.bpm or 0,
            "version": row.version,
            "rights": row.rights,
            "difficulties": row.difficulties or {},
            "image_name": "",
            "release_date": "",
            "is_new": False,
            "is_locked": False,
            "comment": "",
            "aliases": aliases,
        })

    # ── 渲染 ──
    async def render_song_image(self, song_data: SongData) -> bytes:
        return await _render_img(song_data)

    def clear_image_cache(self) -> None:
        _clear_cache()

    # ── 可选钩子 ──
    async def fetch_collections(self, song_id: int) -> list[dict[str, Any]]:
        return []  # CHUNITHM 无收藏信息

    async def fetch_raw_data(self) -> dict[int, SongData]:
        return await fetch_chunithm_raw_data()  # type: ignore[return-value]


# 注册为全局适配器（替换旧的 ChunithmSongQueryAdapter 单例）
from ...shared.search.song_query_adapter import register_game_adapter as _reg

_chuni_adapter = ChunithmDomainAdapter()
_reg("chunithm", _chuni_adapter)


def get_chunithm_adapter() -> ChunithmDomainAdapter:
    return _chuni_adapter
