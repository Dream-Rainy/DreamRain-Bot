"""Game-domain adapter contracts.

Shared query, sync, command, and render code depends on these contracts only.
Each game keeps its own field mapping and special behavior in its domain
adapter implementation.
"""

from __future__ import annotations

from typing import Iterable, Mapping, Protocol, runtime_checkable

from ..song_data import SongData
from .metadata import NaturalRandomPattern


@runtime_checkable
class SongQueryAdapter(Protocol):
    """Minimal contract required by shared song search."""

    game_code: str

    def get_song_store(self) -> Mapping[int, SongData]:
        """Return the current in-memory full song cache, if one is loaded."""
        ...

    def get_song_index(self) -> Mapping[int, str]:
        """Return a lightweight song index: song_id -> title."""
        ...

    def get_song_title(self, song_data: SongData) -> str:
        """Extract a display title from a game-specific song model."""
        ...

    async def get_song_by_id(self, song_id: int) -> SongData | None:
        """Load one full song by ID from persistent storage."""
        ...

    async def load_all_songs(self) -> Mapping[int, SongData]:
        """Load all full songs on demand for workflows that must scan charts."""
        ...

    async def query_alias_exact(self, alias_lower: str) -> list[tuple[int, str]]:
        """Query exact aliases case-insensitively."""
        ...

    async def load_alias_records(self) -> Iterable[tuple[int, str]]:
        """Load all alias rows for fuzzy alias cache construction."""
        ...

    async def get_song_aliases_for_song_id(self, song_id: int) -> list[str]:
        """Load all aliases for one song using game-specific ordering rules."""
        ...

    async def get_song_with_difficulty(
        self,
        song_id: int,
        song_type: str = "standard",
        level_index: int = 3,
    ) -> dict | None:
        """Optionally return a song plus a selected difficulty sheet."""
        ...


@runtime_checkable
class DomainAdapter(SongQueryAdapter, Protocol):
    """Full game-domain adapter contract used outside search."""

    display_name: str
    command_prefix: str
    select_aliases: list[str]
    enable_cross_game_search: bool
    natural_random_patterns: list[NaturalRandomPattern]
    level_names: list[str]
    difficulty_types: list[str]
    async def render_song_image(self, song_data: SongData) -> bytes:
        """Render a song-info image."""
        ...

    def clear_image_cache(self) -> None:
        """Clear game-specific rendered image cache."""
        ...

    async def fetch_collections(self, song_id: int) -> list[dict[str, Any]]:
        """Fetch optional song collections. Games without this return an empty list."""
        ...

    async def fetch_raw_data(self) -> dict[int, SongData]:
        """Fetch and merge the full remote song catalog."""
        ...
