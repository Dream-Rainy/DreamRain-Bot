"""Maimai DomainAdapter — 完整实现。"""

from __future__ import annotations

from typing import Any

from ...infra.db.models import MaiSong, MaiSongAlias
from ...shared.domain_adapter import DomainAdapter
from ...shared.song_data import SongData
from ..maimai.schemas import MaiSongData
from ..maimai.services.song_query import MaimaiSongQueryAdapter
from ..maimai.views import clear_all_img_cache as _clear_all_img_cache
from ..maimai.views.mai_bg_draw import render_song_info_img as _render_song_info_img
from ..maimai.services.collections import fetch_and_update_collections as _fetch_collections
from ..maimai.services.maimai_data_fetcher import fetch_maimai_raw_data


class MaimaiDomainAdapter(MaimaiSongQueryAdapter, DomainAdapter):
    """maimai 域完整适配器。"""

    # ── 游戏常量 ──
    display_name = "maimai"
    level_names = ["Basic", "Advanced", "Expert", "Master", "Re:Master"]
    difficulty_types = ["standard", "dx"]

    # ── 数据同步 ──
    temp_id_threshold = 10000000

    def get_db_song_model(self) -> type:
        return MaiSong

    def get_db_alias_model(self) -> type:
        return MaiSongAlias

    def song_to_db_defaults(self, song: SongData) -> dict[str, Any]:
        diffs = getattr(song, "difficulties", None) or {}
        return {
            "title": song.title,
            "artist": getattr(song, "artist", None),
            "category": getattr(song, "category", None),
            "bpm": getattr(song, "bpm", None),
            "version": getattr(song, "version", None),
            "rights": getattr(song, "rights", None),
            "mai_map": getattr(song, "mai_map", None),
            "release_date": getattr(song, "release_date", None),
            "is_new": getattr(song, "is_new", False),
            "is_locked": getattr(song, "is_locked", False),
            "comment": getattr(song, "comment", None),
            "difficulties": {
                t: [s.model_dump(mode="json", by_alias=True, exclude_none=True) for s in sheets]
                for t, sheets in diffs.items()
            },
        }

    def song_from_db_row(self, row: Any, aliases: list[str]) -> SongData:
        return MaiSongData.from_dict({
            "id": row.id,
            "title": row.title,
            "artist": row.artist,
            "category": row.category,
            "bpm": row.bpm,
            "version": row.version,
            "rights": row.rights,
            "mai_map": row.mai_map,
            "release_date": row.release_date,
            "is_new": row.is_new,
            "is_locked": row.is_locked,
            "comment": row.comment,
            "difficulties": row.difficulties or {},
            "collections": row.collections or [],
            "aliases": aliases,
            "image_name": "",
        })

    # ── 渲染 ──
    async def render_song_image(self, song_data: SongData) -> bytes:
        return await _render_song_info_img(song_data)

    def clear_image_cache(self) -> None:
        _clear_all_img_cache()

    # ── 可选钩子 ──
    async def fetch_collections(self, song_id: int) -> list[dict[str, Any]]:
        return await _fetch_collections(song_id)

    async def fetch_raw_data(self) -> dict[int, SongData]:
        return await fetch_maimai_raw_data()  # type: ignore[return-value]


# 注册为全局适配器（替换旧的 MaimaiSongQueryAdapter 单例）
from ...shared.search.song_query_adapter import register_game_adapter as _reg

_maimai_adapter = MaimaiDomainAdapter()
_reg("maimai", _maimai_adapter)


def get_maimai_adapter() -> MaimaiDomainAdapter:
    return _maimai_adapter
