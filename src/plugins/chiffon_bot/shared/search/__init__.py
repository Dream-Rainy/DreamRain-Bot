"""搜索/匹配相关的通用工具。"""

from .compare import fuzzy_matching_by_song_name
from .song_query import (
    GameCode,
    MatchType,
    SongQueryResult,
    get_song_aliases,
    get_song_data,
    get_song_data_from_id,
    get_song_with_difficulty,
    invalidate_alias_cache,
    query_song_by_alias_exact,
    query_song_by_id,
    query_song_by_title_exact,
    query_song_fuzzy,
    search_song,
)
from ..game import (
    SongQueryAdapter,
    get_game_adapter,
    register_game_adapter,
)

__all__ = [
    "fuzzy_matching_by_song_name",
    # song query
    "GameCode",
    "MatchType",
    "SongQueryResult",
    "get_song_aliases",
    "get_song_data",
    "get_song_data_from_id",
    "get_song_with_difficulty",
    "invalidate_alias_cache",
    "query_song_by_alias_exact",
    "query_song_by_id",
    "query_song_by_title_exact",
    "query_song_fuzzy",
    "search_song",
    # adapters
    "SongQueryAdapter",
    "register_game_adapter",
    "get_game_adapter",
]
