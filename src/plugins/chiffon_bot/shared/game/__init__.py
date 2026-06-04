"""Shared game-domain contracts and adapter registry."""

from .adapter import DomainAdapter, SongQueryAdapter
from .db_song_adapter import DbSongAdapter
from .metadata import NaturalRandomPattern
from .registry import (
    get_domain_adapter,
    get_game_adapter,
    invalidate_adapters,
    iter_domain_adapters,
    iter_game_adapters,
    iter_searchable_adapters,
    register_game_adapter,
)

__all__ = [
    "DbSongAdapter",
    "DomainAdapter",
    "NaturalRandomPattern",
    "SongQueryAdapter",
    "get_domain_adapter",
    "get_game_adapter",
    "invalidate_adapters",
    "iter_domain_adapters",
    "iter_game_adapters",
    "iter_searchable_adapters",
    "register_game_adapter",
]
