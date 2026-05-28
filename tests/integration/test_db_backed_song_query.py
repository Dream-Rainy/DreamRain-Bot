from __future__ import annotations

import math

import pytest

from tests.fixtures.song_seed import (
    CHUNI_ALIAS,
    CHUNI_SONG_ID,
    CHUNI_SONG_TITLE,
    MAI_ALIAS,
    MAI_SONG_ID,
    MAI_SONG_TITLE,
)


pytestmark = pytest.mark.asyncio


async def test_song_index_and_id_loaders(seeded_song_db, song_indexes):
    from src.plugins.chiffon_bot.domains.maimai.services.song_data_sync import (
        load_chuni_song_by_id_from_db,
        load_chuni_song_index_from_db,
        load_mai_song_by_id_from_db,
        load_mai_song_index_from_db,
    )

    assert await load_mai_song_index_from_db() == {MAI_SONG_ID: MAI_SONG_TITLE}
    assert await load_chuni_song_index_from_db() == {CHUNI_SONG_ID: CHUNI_SONG_TITLE}

    mai_song = await load_mai_song_by_id_from_db(MAI_SONG_ID)
    assert mai_song is not None
    assert mai_song.id == MAI_SONG_ID
    assert mai_song.title == MAI_SONG_TITLE
    assert MAI_ALIAS in mai_song.aliases

    chuni_song = await load_chuni_song_by_id_from_db(CHUNI_SONG_ID)
    assert chuni_song is not None
    assert chuni_song.id == CHUNI_SONG_ID
    assert chuni_song.title == CHUNI_SONG_TITLE
    assert CHUNI_ALIAS in chuni_song.aliases


async def test_search_uses_index_and_loads_full_song_on_demand(seeded_song_db, song_indexes):
    from src.plugins.chiffon_bot.shared.search.song_query import (
        get_song_aliases,
        get_song_with_difficulty,
        query_song_by_alias_exact,
        query_song_by_title_exact,
        search_song,
    )

    by_id = await search_song(MAI_SONG_ID, game_code="maimai")
    assert by_id
    assert by_id[0].song_id == MAI_SONG_ID
    assert by_id[0].song_data.title == MAI_SONG_TITLE

    by_title = await query_song_by_title_exact(MAI_SONG_TITLE, game_code="maimai")
    assert by_title
    assert by_title[0].song_id == MAI_SONG_ID

    by_alias = await query_song_by_alias_exact(MAI_ALIAS, game_code="maimai")
    assert by_alias
    assert by_alias[0].song_id == MAI_SONG_ID

    aliases = await get_song_aliases(MAI_SONG_ID, game_code="maimai")
    assert aliases is not None
    assert MAI_ALIAS in aliases["aliases"]

    diff = await get_song_with_difficulty(
        MAI_SONG_ID,
        song_type="dx",
        level_index=0,
        game_code="maimai",
    )
    assert diff is not None
    assert diff["song_data"].id == MAI_SONG_ID
    assert diff["target_difficulty"].level == "13+"

    chuni_result = await search_song(CHUNI_SONG_TITLE, game_code="chunithm")
    assert chuni_result
    assert chuni_result[0].song_id == CHUNI_SONG_ID
    assert chuni_result[0].song_data.title == CHUNI_SONG_TITLE

    assert song_indexes.mai_song_data == {}
    assert song_indexes.chuni_song_data == {}


async def test_adapters_can_load_random_candidates_without_persistent_full_cache(
    seeded_song_db,
    song_indexes,
):
    from src.plugins.chiffon_bot.shared.handlers.generic_random_song import (
        get_songs_by_difficulty_range,
    )
    from src.plugins.chiffon_bot.shared.search.song_query_adapter import get_game_adapter

    mai_adapter = get_game_adapter("maimai")
    chuni_adapter = get_game_adapter("chunithm")

    mai_songs = await mai_adapter.load_all_songs()
    mai_candidates = get_songs_by_difficulty_range(mai_songs, 0.0, math.inf, mai_adapter)
    assert mai_candidates
    assert any(c["song_data"].id == MAI_SONG_ID for c in mai_candidates)

    chuni_songs = await chuni_adapter.load_all_songs()
    chuni_candidates = get_songs_by_difficulty_range(chuni_songs, 0.0, math.inf, chuni_adapter)
    assert chuni_candidates
    assert any(c["song_data"].id == CHUNI_SONG_ID for c in chuni_candidates)

    assert song_indexes.mai_song_data == {}
    assert song_indexes.chuni_song_data == {}
