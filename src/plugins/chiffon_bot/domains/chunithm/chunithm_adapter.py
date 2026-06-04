"""CHUNITHM DomainAdapter — 完整实现。"""

from __future__ import annotations

from typing import Any

from ...infra.db.models import ChuniSong, ChuniSongAlias
from ...shared.game.adapter import DomainAdapter
from ...shared.game.db_song_adapter import DbSongAdapter
from ...shared.game.metadata import NaturalRandomPattern
from ...shared.game.registry import register_game_adapter as _reg
from ...shared.song_data import SongData
from ..chunithm.schemas import ChuniSongData
from ..chunithm.views.chuni_bg_draw import (
    render_chuni_song_info_img as _render_img,
    clear_chuni_song_info_img_cache as _clear_cache,
)
from ..chunithm.services.chunithm_data_fetcher import (
    build_chuni_jacket_image_name,
    fetch_chunithm_raw_data,
)


class ChunithmDomainAdapter(DbSongAdapter, DomainAdapter):
    """CHUNITHM 域完整适配器。"""

    # ── 游戏常量 ──
    display_name = "CHUNITHM"
    command_prefix = "chuni"
    select_aliases = ["chunithm", "chuni", "中二", "中二节奏"]
    enable_cross_game_search = True
    natural_random_patterns = [
        NaturalRandomPattern(r"^chunithm随机(?:一首)?(?:歌|乐曲|曲子)?[？?]?$"),
        NaturalRandomPattern(r"^随机(?:一首)?chunithm(?:歌|乐曲|曲子)?[？?]?$"),
        NaturalRandomPattern(
            r"^chunithm随机([0-9.]+\+?)(?:难度)?(?:的)?(?:歌|乐曲|曲子)?[？?]?$",
            1,
        ),
        NaturalRandomPattern(
            r"^chunithm随机([0-9.]+)-([0-9.]+)(?:难度)?(?:的)?(?:歌|乐曲|曲子)?[？?]?$",
            2,
        ),
        NaturalRandomPattern(
            r"^chunithm随机([0-9.]+)到([0-9.]+)(?:难度)?(?:的)?(?:歌|乐曲|曲子)?[？?]?$",
            2,
        ),
    ]
    level_names = ["BASIC", "ADVANCED", "EXPERT", "MASTER", "ULTIMA"]
    difficulty_types = ["standard", "ultima"]

    # ── 数据同步 ──
    temp_id_threshold = 100000
    game_code = "chunithm"
    song_store_attr = "chuni_song_data"
    song_index_attr = "chuni_song_index"
    dedupe_aliases_for_display = True

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
            "image_name": getattr(song, "image_name", "") or "",
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
            "image_name": row.image_name or build_chuni_jacket_image_name(row.id),
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


_chuni_adapter = ChunithmDomainAdapter()
_reg("chunithm", _chuni_adapter)


def get_chunithm_adapter() -> ChunithmDomainAdapter:
    return _chuni_adapter
