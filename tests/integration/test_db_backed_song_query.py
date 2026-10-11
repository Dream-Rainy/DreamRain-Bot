from __future__ import annotations

import math

import pytest


async def test_scoped_and_global_queries_share_work_level_rejection(seeded_song_db, monkeypatch):
    from arcade_helper.catalog import CatalogRecord
    from arcade_helper.core.song import SongData
    from arcade_helper.search import MatchType
    from src.plugins.chiffon_bot.integrations.lxns.client import lxns_client as client
    from src.plugins.chiffon_bot.shared.search import reranker
    from src.plugins.chiffon_bot.integrations.lxns import catalog as module
    for game in ("sdvx", "ongeki"):
        songs = [SongData(id=i, title=f"Fruit {name}", artist="composer", aliases=["红苹果"])
                 for i, name in enumerate(("One", "Two"), 1)]
        await client.identities.import_records(game, [CatalogRecord(s, s.model_dump(mode="json"), str(s.id)) for s in songs],
                                               provider="catalog", namespace="native", complete=False)
    calls, full_reads = [], []
    score = 0.1
    async def rank(query, documents):
        calls.append(documents)
        return [score, 0.0]
    original = client.catalog.get_songs_by_ids
    async def full(*args):
        full_reads.append(args)
        return await original(*args)
    monkeypatch.setattr(client.catalog, "get_songs_by_ids", full)
    monkeypatch.setattr(module, "reranker_enabled", lambda: True)
    monkeypatch.setattr(reranker, "reranker_enabled", lambda: True)
    monkeypatch.setattr(reranker, "reranker_threshold", lambda: 0.6)
    monkeypatch.setattr(reranker, "reranker_min_margin", lambda: 0.1)
    monkeypatch.setattr(reranker, "rerank_texts", rank)
    text = await client.catalog.search_all("composer 红苹果", allow_semantic=False)
    assert len(text.candidates) == 4 and {c.match_type for c in text.candidates} == {MatchType.BM25.value}
    assert not (await client.catalog.search_all("composer 红苹果")).candidates
    assert await client.catalog.search_song("sdvx", "composer 红苹果") == []
    assert len(calls) == 2 and all(len(batch) == 2 for batch in calls) and not full_reads
    score = 0.9
    global_rows = (await client.catalog.search_all("composer 红苹果")).candidates
    scoped = await client.catalog.search_song("sdvx", "composer 红苹果")
    assert {c.title for c in global_rows} == {scoped[0].title}
    assert {c.game_code for c in global_rows} == {"sdvx", "ongeki"}
    assert len(full_reads) == 1

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
    from arcade_helper.storage.tortoise.models import MaiSongAlias

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

    updated = MaiSongData(
        id=song_id,
        title="Updated Sync Test Song",
        artist="tester",
        category="niconico",
        bpm=180,
        version="PRiSM",
        image_name="jacket/UI_Jacket_002026.png",
        aliases=["sync-test", "new-alias"],
        difficulties=MAI_DIFFICULTIES,
    )
    await store.sync_songs("maimai", {song_id: updated})

    loaded = await store.get_song_by_id("maimai", song_id)
    assert loaded is not None
    assert loaded.title == "Updated Sync Test Song"
    assert await MaiSongAlias.filter(song_id=song_id, alias="sync-test").count() == 1
    assert "new-alias" in await store.get_song_aliases_for_song_id("maimai", song_id)


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


async def test_sql_exact_and_ranking_use_light_catalog(seeded_song_db, monkeypatch):
    from src.plugins.chiffon_bot.integrations.lxns.client import lxns_client as client
    from arcade_helper.catalog import CatalogRecord
    from arcade_helper.core.song import SongData
    async def forbidden(*args, **kwargs):
        raise AssertionError('query loaded the full catalog')
    monkeypatch.setattr(client.catalog, 'load_all_songs', forbidden)
    monkeypatch.setattr(client.data.catalog, 'load_all_songs', forbidden)
    monkeypatch.setattr(client.identities, '_cached_songs', forbidden)
    assert [r.song_id for r in await client.catalog.search_song('maimai', MAI_SONG_TITLE)] == [MAI_SONG_ID]
    assert [r.song_id for r in await client.catalog.search_song('maimai', MAI_ALIAS)] == [MAI_SONG_ID]
    assert await client.catalog.search_song('maimai', MAI_SONG_TITLE[:3]) == []
    assert [r.song_id for r in await client.catalog.search_song('maimai', MAI_SONG_TITLE[:-1])] == [MAI_SONG_ID]
    # A numeric title remains a separate candidate alongside an actual numeric ID.
    song = SongData(id=99999, title=str(MAI_SONG_ID), artist='Other')
    await client.identities.import_records('maimai', [CatalogRecord(song, song.model_dump(mode='json'), '99999')],
                                           provider='catalog', namespace='native', complete=False)
    from arcade_helper.storage.tortoise.models import MaiSong
    await MaiSong.create(id=99999, title=str(MAI_SONG_ID), artist='Other')
    matches = await client.catalog.service.query_title_exact('maimai', str(MAI_SONG_ID))
    assert matches == [(99999, str(MAI_SONG_ID))]
    assert {r.song_id for r in await client.catalog.search_song('maimai', str(MAI_SONG_ID))} == {MAI_SONG_ID, 99999}
    metadata = await client.catalog.load_search_songs('maimai')
    assert metadata[MAI_SONG_ID].artist and not metadata[MAI_SONG_ID].difficulties


async def test_full_candidate_batches_have_bounded_queries_and_correct_public_ids(seeded_song_db, monkeypatch):
    from arcade_helper.catalog import CatalogRecord
    from arcade_helper.core.song import SongData, SongSheet
    from arcade_helper.storage.tortoise.catalog_models import AliasRevision, GameSong
    from tortoise.expressions import F
    from src.plugins.chiffon_bot.integrations.lxns.client import lxns_client as client

    base = await client.catalog.get_song_by_id("maimai", MAI_SONG_ID)
    native_ids = [41001, 41002, 41003, 41004, 41005]
    native = {sid: base.model_copy(update={"id": sid, "title": f"Batch Song {sid}", "aliases": [f"native-{sid}"]})
              for sid in native_ids}
    await client.data.catalog.sync_songs("maimai", native)
    generic = [SongData(id=sid, title=f"Batch Song {sid}", artist="Batch Artist", aliases=[f"generic-{sid}"],
        image_name=f"{sid}.jpg", difficulties={"standard": [SongSheet(type="standard", difficulty="master", level="15")]})
        for sid in range(5)]
    report = await client.identities.import_records("sdvx", [
        CatalogRecord(song, song.model_dump(mode="json"), str(song.id)) for song in generic
    ], provider="catalog", namespace="native")
    generic_ids = list(report.song_ids.values())
    db = client.identities._db
    queries = []
    for name in ("execute_query", "execute_query_dict"):
        original = getattr(db, name)
        async def counted(sql, *args, _original=original, **kwargs):
            queries.append(sql)
            return await _original(sql, *args, **kwargs)
        monkeypatch.setattr(db, name, counted)

    for game, ids in (("maimai", native_ids), ("sdvx", generic_ids)):
        queries.clear()
        two = await client.catalog.get_songs_by_ids(game, ids[:2])
        small_count = len(queries)
        queries.clear()
        requested = [ids[-1], *ids, ids[0], 99999999]
        all_songs = await client.catalog.get_songs_by_ids(game, requested)
        assert len(queries) == small_count  # SQL round trips do not grow per candidate.
        assert list(all_songs) == list(dict.fromkeys(requested))[:-1]
        assert set(two) == set(ids[:2])
        assert all(song.id == sid and song.image_name and song.difficulties and song.aliases
                   for sid, song in all_songs.items())
        if game == "maimai":
            assert all_songs[ids[0]].difficulties["dx"][0].level == "13+"
        else:
            assert all_songs[ids[0]].difficulties["standard"][0].level == "15"

    async def forbidden(*args, **kwargs):
        raise AssertionError("fuzzy candidate used sequential full-song reads")
    monkeypatch.setattr(client.catalog, "get_song_by_id", forbidden)
    # Recall from lightweight metadata, then hydrate only the returned candidates.
    matches = await client.catalog.search.query_song_fuzzy("Batch Song", threshold=50, game_code="sdvx")
    assert len(matches) > 1 and all(r.song_data.image_name and r.song_data.difficulties for r in matches)
    target = generic_ids[0]
    await GameSong.filter(id=target).update(active=False)
    await AliasRevision.filter(id=1).update(revision=F("revision") + 1)
    assert target not in await client.catalog.get_songs_by_ids("sdvx", generic_ids)
