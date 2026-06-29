from __future__ import annotations

import math

import pytest

from tests.fixtures.song_seed import (
    CHUNI_ALIAS,
    CHUNI_SONG_ID,
    CHUNI_SONG_TITLE,
    MAI_DIFFICULTIES,
    MAI_ALIAS,
    MAI_SONG_ID,
    MAI_SONG_TITLE,
)


pytestmark = pytest.mark.asyncio


async def test_song_index_and_id_loaders(seeded_song_db, song_indexes):
    from src.plugins.chiffon_bot.integrations.lxns.client import lxns_client

    assert await lxns_client.catalog.load_song_index("maimai") == {MAI_SONG_ID: MAI_SONG_TITLE}
    assert await lxns_client.catalog.load_song_index("chunithm") == {CHUNI_SONG_ID: CHUNI_SONG_TITLE}

    mai_song = await lxns_client.catalog.get_song_by_id("maimai", MAI_SONG_ID)
    assert mai_song is not None
    assert mai_song.id == MAI_SONG_ID
    assert mai_song.title == MAI_SONG_TITLE
    assert mai_song.image_name == "jacket/UI_Jacket_000181.png"
    assert MAI_ALIAS in mai_song.aliases

    chuni_song = await lxns_client.catalog.get_song_by_id("chunithm", CHUNI_SONG_ID)
    assert chuni_song is not None
    assert chuni_song.id == CHUNI_SONG_ID
    assert chuni_song.title == CHUNI_SONG_TITLE
    assert chuni_song.image_name == "jacket/CHU_UI_Jacket_000001.png"
    assert CHUNI_ALIAS in chuni_song.aliases


async def test_tortoise_song_store_queries_seeded_catalog(seeded_song_db):
    from arcade_helper.storage.tortoise import TortoiseSongStore

    store = TortoiseSongStore()

    assert await store.load_song_index("maimai") == {MAI_SONG_ID: MAI_SONG_TITLE}
    assert await store.load_song_index("chunithm") == {CHUNI_SONG_ID: CHUNI_SONG_TITLE}

    mai_song = await store.get_song_by_id("maimai", MAI_SONG_ID)
    assert mai_song is not None
    assert mai_song.title == MAI_SONG_TITLE
    assert MAI_ALIAS in mai_song.aliases

    aliases = await store.query_alias_exact("maimai", MAI_ALIAS)
    assert aliases == [(MAI_SONG_ID, MAI_ALIAS)]

    diff = await store.get_song_with_difficulty(
        "maimai",
        MAI_SONG_ID,
        song_type="dx",
        level_index=3,
    )
    assert diff is not None
    assert diff["song_data"].id == MAI_SONG_ID

    assert await store.get_song_with_difficulty("chunithm", CHUNI_SONG_ID) is None


async def test_tortoise_song_store_syncs_song_catalog(seeded_song_db):
    from arcade_helper.games.maimai.schemas import MaiSongData
    from arcade_helper.storage.tortoise import TortoiseSongStore

    store = TortoiseSongStore()
    song_id = 2026
    song = MaiSongData(
        id=song_id,
        title="Sync Test Song",
        artist="tester",
        category="niconico",
        bpm=180,
        version="PRiSM",
        image_name="jacket/UI_Jacket_002026.png",
        aliases=["sync-test", "Sync Test Song", "sync-test"],
        difficulties=MAI_DIFFICULTIES,
    )

    await store.sync_songs("maimai", {song_id: song})

    loaded = await store.get_song_by_id("maimai", song_id)
    assert loaded is not None
    assert loaded.title == "Sync Test Song"
    assert await store.get_song_aliases_for_song_id("maimai", song_id) == [
        "sync-test",
        "Sync Test Song",
    ]


async def test_search_uses_index_and_loads_full_song_on_demand(seeded_song_db, song_indexes):
    from src.plugins.chiffon_bot.integrations.lxns.client import lxns_client

    by_id = await lxns_client.data.catalog.search_song("maimai", MAI_SONG_ID)
    assert by_id
    assert by_id[0].song_id == MAI_SONG_ID
    assert by_id[0].song_data.title == MAI_SONG_TITLE

    by_title = await lxns_client.data.catalog.query_song_by_title_exact("maimai", MAI_SONG_TITLE)
    assert by_title
    assert by_title[0].song_id == MAI_SONG_ID

    by_alias = await lxns_client.data.catalog.query_song_by_alias_exact("maimai", MAI_ALIAS)
    assert by_alias
    assert by_alias[0].song_id == MAI_SONG_ID

    aliases = await lxns_client.data.catalog.get_song_aliases("maimai", MAI_SONG_ID)
    assert aliases is not None
    assert MAI_ALIAS in aliases["aliases"]

    diff = await lxns_client.data.catalog.get_song_with_difficulty(
        "maimai",
        MAI_SONG_ID,
        song_type="dx",
        level_index=0,
    )
    assert diff is not None
    assert diff["song_data"].id == MAI_SONG_ID
    assert diff["target_difficulty"].level == "13+"

    chuni_result = await lxns_client.data.catalog.search_song("chunithm", CHUNI_SONG_TITLE)
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
    from src.plugins.chiffon_bot.shared.game.registry import get_game_adapter

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


async def test_game_adapters_are_registered_from_shared_game_layer(loaded_chiffon_bot):
    from src.plugins.chiffon_bot.shared.game import CatalogSongAdapter, get_game_adapter

    mai_adapter = get_game_adapter("maimai")
    chuni_adapter = get_game_adapter("chunithm")

    assert isinstance(mai_adapter, CatalogSongAdapter)
    assert isinstance(chuni_adapter, CatalogSongAdapter)
    assert type(chuni_adapter).__module__.endswith("domains.chunithm.chunithm_adapter")
