"""CHUNITHM song DB sync and load helpers."""

from __future__ import annotations

from ..schemas import ChuniSongData
from ....shared.generic_sync import generic_sync_to_db


def _adapter():
    from ..chunithm_adapter import get_chunithm_adapter

    return get_chunithm_adapter()


async def sync_chuni_song_data(song_data: dict[int, ChuniSongData]) -> None:
    """Sync CHUNITHM songs to the local database."""

    await generic_sync_to_db(_adapter(), song_data)  # type: ignore[arg-type]


async def load_chuni_song_data_from_db() -> dict[int, ChuniSongData]:
    """Load all CHUNITHM songs from the local database."""

    return await _adapter().load_all_songs()  # type: ignore[return-value]


async def load_chuni_song_index_from_db() -> dict[int, str]:
    """Load a lightweight CHUNITHM song index from the local database."""

    return await _adapter().load_song_index_from_db()


async def load_chuni_song_by_id_from_db(song_id: int) -> ChuniSongData | None:
    """Load one CHUNITHM song from the local database."""

    return await _adapter().get_song_by_id(song_id)  # type: ignore[return-value]
