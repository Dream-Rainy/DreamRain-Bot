"""Shared game-domain contracts and adapter registry."""

from .adapter import DomainAdapter, SongQueryAdapter
from .catalog_song_adapter import CatalogSongAdapter
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
    "CatalogSongAdapter",
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
