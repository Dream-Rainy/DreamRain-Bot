"""Maimai DomainAdapter — 完整实现。"""

from __future__ import annotations

from typing import Any

from ...shared.game.adapter import DomainAdapter
from ...shared.game.catalog_song_adapter import CatalogSongAdapter
from ...shared.game.metadata import NaturalRandomPattern
from ...shared.game.registry import register_game_adapter as _reg
from ...shared.song_data import SongData
from ..maimai.views import clear_all_img_cache as _clear_all_img_cache
from ..maimai.views.mai_bg_draw import render_song_info_img as _render_song_info_img
from ..maimai.services.collections import fetch_and_update_collections as _fetch_collections


class MaimaiDomainAdapter(CatalogSongAdapter, DomainAdapter):
    """maimai 域完整适配器。"""

    # ── 游戏常量 ──
    display_name = "maimai"
    command_prefix = "mai"
    select_aliases = ["maimai", "mai", "舞萌"]
    enable_cross_game_search = True
    natural_random_patterns = [
        NaturalRandomPattern(r"^随机(?:一首)?(?:歌|乐曲|曲子)?[？?]?$"),
        NaturalRandomPattern(r"^来首?随机(?:歌|乐曲|曲子)?[？?]?$"),
        NaturalRandomPattern(
            r"^(?:随机|来首?)(?:一首)?([0-9.]+\+?)(?:难度)?(?:的)?(?:歌|乐曲|曲子)?[？?]?$",
            1,
        ),
        NaturalRandomPattern(
            r"^(?:随机|来首?)(?:一首)?([0-9.]+)-([0-9.]+)(?:难度)?(?:的)?(?:歌|乐曲|曲子)?[？?]?$",
            2,
        ),
        NaturalRandomPattern(
            r"^(?:随机|来首?)(?:一首)?([0-9.]+)到([0-9.]+)(?:难度)?(?:的)?(?:歌|乐曲|曲子)?[？?]?$",
            2,
        ),
    ]
    level_names = ["Basic", "Advanced", "Expert", "Master", "Re:Master"]
    difficulty_types = ["standard", "dx"]

    # ── 曲库缓存 ──
    game_code = "maimai"
    song_store_attr = "mai_song_data"
    song_index_attr = "mai_song_index"

    # ── 渲染 ──
    async def render_song_image(self, song_data: SongData) -> bytes:
        return await _render_song_info_img(song_data)

    def clear_image_cache(self) -> None:
        _clear_all_img_cache()

    # ── 可选钩子 ──
    async def fetch_collections(self, song_id: int) -> list[dict[str, Any]]:
        return await _fetch_collections(song_id)

    async def fetch_raw_data(self) -> dict[int, SongData]:
        from ...integrations.lxns.client import lxns_client

        return await lxns_client.catalog.fetch_maimai_raw_data()  # type: ignore[return-value]


_maimai_adapter = MaimaiDomainAdapter()
_reg("maimai", _maimai_adapter)


def get_maimai_adapter() -> MaimaiDomainAdapter:
    return _maimai_adapter
