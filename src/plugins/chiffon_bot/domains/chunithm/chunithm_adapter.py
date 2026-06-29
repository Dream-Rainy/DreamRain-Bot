"""CHUNITHM DomainAdapter — 完整实现。"""

from __future__ import annotations

from typing import Any

from ...shared.game.adapter import DomainAdapter
from ...shared.game.catalog_song_adapter import CatalogSongAdapter
from ...shared.game.metadata import NaturalRandomPattern
from ...shared.game.registry import register_game_adapter as _reg
from ...shared.song_data import SongData
from ..chunithm.views.chuni_bg_draw import (
    render_chuni_song_info_img as _render_img,
    clear_chuni_song_info_img_cache as _clear_cache,
)


class ChunithmDomainAdapter(CatalogSongAdapter, DomainAdapter):
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

    # ── 曲库缓存 ──
    game_code = "chunithm"
    song_store_attr = "chuni_song_data"
    song_index_attr = "chuni_song_index"

    # ── 渲染 ──
    async def render_song_image(self, song_data: SongData) -> bytes:
        return await _render_img(song_data)

    def clear_image_cache(self) -> None:
        _clear_cache()

    # ── 可选钩子 ──
    async def fetch_collections(self, song_id: int) -> list[dict[str, Any]]:
        return []  # CHUNITHM 无收藏信息

    async def fetch_raw_data(self) -> dict[int, SongData]:
        from ...integrations.lxns.client import lxns_client

        return await lxns_client.catalog.fetch_chunithm_raw_data()  # type: ignore[return-value]


_chuni_adapter = ChunithmDomainAdapter()
_reg("chunithm", _chuni_adapter)


def get_chunithm_adapter() -> ChunithmDomainAdapter:
    return _chuni_adapter
