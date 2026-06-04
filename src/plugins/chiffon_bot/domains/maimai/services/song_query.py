"""Compatibility exports for shared song query.

The search implementation and adapter registry now live in ``shared.search``
and ``shared.game``.  This file remains only for old imports.
"""

from __future__ import annotations

from typing import Literal

from ....shared.search.song_query import (
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

GameCode = Literal["maimai", "chunithm"]

__all__ = [
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
]
