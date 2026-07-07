"""搜索/匹配相关的通用工具。"""

from .compare import fuzzy_matching_by_song_name
from ..game import (
    SongQueryAdapter,
    get_game_adapter,
    register_game_adapter,
)

__all__ = [
    "fuzzy_matching_by_song_name",
    # adapters
    "SongQueryAdapter",
    "register_game_adapter",
    "get_game_adapter",
]
