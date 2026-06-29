"""Adapter bridge from game metadata to the centralized catalog client."""

from __future__ import annotations

from typing import Mapping

from ...integrations.lxns.plugin_data import plugin_data
from ..song_data import SongData


class CatalogSongAdapter:
    """Bridge legacy search contracts to ``lxns_client.catalog``."""

    game_code: str
    song_store_attr: str
    song_index_attr: str

    def get_song_store(self) -> Mapping[int, SongData]:
        return getattr(plugin_data, self.song_store_attr)

    def get_song_index(self) -> Mapping[int, str]:
        return getattr(plugin_data, self.song_index_attr)

    def get_song_title(self, song_data: SongData) -> str:
        return str(getattr(song_data, "title", "") or "")

    async def get_song_by_id(self, song_id: int) -> SongData | None:
        from ...integrations.lxns.client import lxns_client

        return await lxns_client.catalog.get_song_by_id(self.game_code, song_id)

    async def load_all_songs(self) -> dict[int, SongData]:
        from ...integrations.lxns.client import lxns_client

        return await lxns_client.catalog.load_all_songs(self.game_code)  # type: ignore[return-value]

    async def query_alias_exact(self, alias_lower: str) -> list[tuple[int, str]]:
        from ...integrations.lxns.client import lxns_client

        return await lxns_client.catalog.query_alias_exact(self.game_code, alias_lower)

    async def load_alias_records(self) -> list[tuple[int, str]]:
        from ...integrations.lxns.client import lxns_client

        return await lxns_client.catalog.load_alias_records(self.game_code)

    async def get_song_aliases_for_song_id(self, song_id: int) -> list[str]:
        from ...integrations.lxns.client import lxns_client

        return await lxns_client.catalog.get_song_aliases_for_song_id(self.game_code, song_id)

    async def get_song_with_difficulty(
        self,
        song_id: int,
        song_type: str = "standard",
        level_index: int = 3,
    ) -> dict | None:
        from ...integrations.lxns.client import lxns_client

        return await lxns_client.catalog.get_song_with_difficulty(
            self.game_code,
            song_id,
            song_type=song_type,
            level_index=level_index,
        )


__all__ = ["CatalogSongAdapter"]
