"""Compatibility exports for the shared game adapter registry.

New code should import from ``src.plugins.chiffon_bot.shared.game``.
"""

from ..game.adapter import SongQueryAdapter
from ..game.registry import get_game_adapter, invalidate_adapters, register_game_adapter

__all__ = [
    "SongQueryAdapter",
    "get_game_adapter",
    "invalidate_adapters",
    "register_game_adapter",
]
