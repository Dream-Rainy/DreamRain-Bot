"""Host storage, legacy migration and stale semantic search acceptance checks."""

import pytest

from arcade_helper.aliases.models import AliasConflictError
from arcade_helper.catalog import CatalogRecord
from arcade_helper.core.song import SongData
from arcade_helper.storage.tortoise import migrate_catalog_identities
from arcade_helper.storage.tortoise.alias_models import AliasEvidence
from tests.fixtures.song_seed import MAI_SONG_ID, MAI_SONG_TITLE
from tools.migrate_aliases import migrate_accepted_aliases


async def test_native_identity_scopes_and_legacy_migration(seeded_song_db):
    from src.plugins.chiffon_bot.integrations.lxns.client import lxns_client as client
    internal_id = await client.catalog.internal_song_id("maimai", MAI_SONG_ID)
    assert internal_id != MAI_SONG_ID
    await migrate_catalog_identities(store=client.identities, dry_run=False)
    assert await client.catalog.internal_song_id("maimai", MAI_SONG_ID) == internal_id
    native = await client.catalog.get_song_by_id("maimai", MAI_SONG_ID)
    generic = SongData(id=77, title=native.title, artist=native.artist)
    report = await client.identities.import_records("sdvx", [CatalogRecord(generic, generic.model_dump(mode="json"), "77")],
                                                     provider="fixture", complete=False)
    generic_id = report.song_ids["77"]
    alice = (await client.data.users.from_platform("qq", "123")).user_id
    admin = (await client.data.users.from_platform("qq", "456")).user_id
    client._alias_actors.update({alice: False, admin: True})
    for scope, text in [("work", "共同别名"), ("game_song", "舞萌限定")]:
        request = await client.data.aliases.submit(actor_id=alice, operation="ADD_ALIAS", idempotency_key=scope,
                                                  payload={"game_song_id": internal_id, "text": text, "scope": scope})
        await client.data.aliases.review(request, actor_id=admin, approve=True, expected_version=1, reason="核实范围")
    assert await client.catalog.query_alias_exact("sdvx", "共同别名") == [(generic_id, "共同别名")]
    assert not await client.catalog.query_alias_exact("sdvx", "舞萌限定")
    assert (await client.catalog.get_song_by_id("maimai", MAI_SONG_ID)).id == MAI_SONG_ID

    rows = [{"game": "maimai", "alias_candidate": {"status": "accepted", "song_id": MAI_SONG_ID,
             "title": MAI_SONG_TITLE, "alias": "旧审核简称"}},
            {"game": "sdvx", "status": "accepted", "song_id": 77, "title": native.title, "alias": "旧枚举昵称"}]
    preview = await migrate_accepted_aliases(client.data, rows)
    assert len(preview["ready"]) == 1 and len(preview["unresolved"]) == 1
    assert not (await client.data.aliases.resolve_alias("旧审核简称")).candidates
    with pytest.raises(ValueError, match="身份不明"):
        await migrate_accepted_aliases(client.data, rows, actor_id=admin, apply=True)
    mapping = {"sdvx:77": generic_id}
    await migrate_accepted_aliases(client.data, rows, actor_id=admin, apply=True, mapping=mapping)
    count = await AliasEvidence.all().count()
    await migrate_accepted_aliases(client.data, rows, actor_id=admin, apply=True, mapping=mapping)
    assert await AliasEvidence.all().count() == count
    assert await client.catalog.query_alias_exact("maimai", "旧审核简称") == [(MAI_SONG_ID, "旧审核简称")]
    assert not await client.catalog.query_alias_exact("sdvx", "旧审核简称")
    # A repeat migration must not resurrect a deliberately retracted old alias.
    evidence = await AliasEvidence.filter(raw_text="旧审核简称").first()
    request = await client.data.aliases.submit(actor_id=alice, operation="RETRACT_EVIDENCE",
                                              payload={"evidence_id": evidence.id}, idempotency_key="retire")
    await client.data.aliases.review(request, actor_id=admin, approve=True, expected_version=1, reason="不再使用")
    await migrate_accepted_aliases(client.data, rows, actor_id=admin, apply=True, mapping=mapping)
    assert not await client.catalog.query_alias_exact("maimai", "旧审核简称")


async def test_review_target_change_requires_confirmation(seeded_song_db):
    from src.plugins.chiffon_bot.integrations.lxns.client import lxns_client as client
    alice = (await client.data.users.from_platform("qq", "123")).user_id
    admin = (await client.data.users.from_platform("qq", "456")).user_id
    client._alias_actors.update({alice: False, admin: True})
    internal_id = await client.catalog.internal_song_id("maimai", MAI_SONG_ID)
    request = await client.data.aliases.submit(actor_id=alice, operation="ADD_ALIAS", idempotency_key="conflict",
                                              payload={"game_song_id": internal_id, "text": "目标变更简称"})
    from arcade_helper.storage.tortoise.catalog_models import GameSong
    await GameSong.filter(id=internal_id).update(version=2)
    with pytest.raises(AliasConflictError, match="TARGET_CHANGED"):
        await client.data.aliases.review(request, actor_id=admin, approve=True, expected_version=1, reason="核实")
    detail = await client.data.aliases.get_request(request, actor_id=admin)
    await client.data.aliases.review(request, actor_id=admin, approve=True, expected_version=detail['version'],
                                    expected_target_versions=detail['current_target_versions'], reason="已核实更新后的目标")
    assert await client.catalog.query_alias_exact("maimai", "目标变更简称")


async def test_semantic_cache_invalidated_by_alias_decision(seeded_song_db, monkeypatch, tmp_path):
    from src.plugins.chiffon_bot.integrations.lxns.client import lxns_client as client
    from src.plugins.chiffon_bot.shared.search import embedding_cache
    alice = (await client.data.users.from_platform("qq", "123")).user_id
    admin = (await client.data.users.from_platform("qq", "456")).user_id
    client._alias_actors.update({alice: False, admin: True})
    path = tmp_path / "embeddings.jsonl"
    monkeypatch.setattr(embedding_cache, "embedding_enabled", lambda: True)
    monkeypatch.setattr(embedding_cache, "embedding_path", lambda: path)
    monkeypatch.setenv("SONG_SEARCH_EMBEDDING_ENABLED", "true")
    monkeypatch.setenv("SONG_SEARCH_EMBEDDING_PATH", str(path))
    async def embed(texts):
        return [[1.0, 0.0] for _ in texts]
    await embedding_cache.rebuild_song_embeddings(client.catalog, "maimai", path=path, embedder=embed)
    import json
    with path.open("a", encoding="utf-8") as output:
        output.write(json.dumps({"game": "maimai", "query": "zzzzsemantic", "vector": [1, 0]}) + "\n")
    assert await embedding_cache.search_song_by_embedding(client.catalog, "maimai", "semantic", path=path, embedder=embed)
    request = await client.data.aliases.submit(actor_id=alice, operation="ADD_ALIAS", idempotency_key="revision",
        payload={"game_song_id": await client.catalog.internal_song_id("maimai", MAI_SONG_ID), "text": "新语义简称"})
    # Pending requests leave the effective catalog and existing vectors valid.
    assert await embedding_cache.search_song_by_embedding(client.catalog, "maimai", "semantic", path=path, embedder=embed)
    await client.data.aliases.review(request, actor_id=admin, approve=True, expected_version=1, reason="核实")
    assert not await embedding_cache.search_song_by_embedding(client.catalog, "maimai", "semantic", path=path, embedder=embed)
    assert not await client.catalog.search_song("maimai", "zzzzsemantic")
    await embedding_cache.rebuild_song_embeddings(client.catalog, "maimai", path=path, embedder=embed)
    assert await embedding_cache.search_song_by_embedding(client.catalog, "maimai", "semantic", path=path, embedder=embed)


async def test_host_startup_upgrades_old_catalog_columns(tmp_path, loaded_chiffon_bot):
    import sqlite3
    from src.plugins.chiffon_bot.infra.db.connect import init, close
    path = tmp_path / "old-catalog.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE music_works (id CHAR(36) PRIMARY KEY, display_title TEXT NOT NULL, artist TEXT NOT NULL DEFAULT '')")
    settings = {"engine": "tortoise.backends.sqlite", "credentials": {"file_path": str(path)}}
    try:
        await init(db_settings=settings)
        await init(db_settings=settings)  # Repeated startup must remain safe.
        with sqlite3.connect(path) as db:
            columns = {row[1] for row in db.execute("PRAGMA table_info(music_works)")}
            assert {"version", "redirect_to"} <= columns
            assert db.execute("SELECT COUNT(*) FROM alias_revision WHERE id=1").fetchone()[0] == 1
    finally:
        await close()


async def test_host_backfill_normalizes_width_and_preserves_space_titles_and_formatting(
    tmp_path, loaded_chiffon_bot, monkeypatch
):
    from arcade_helper.storage.tortoise import (
        MaiSong, MaiSongAlias, ChuniSong, ChuniSongAlias, TortoiseCatalogStore,
    )
    from nonebot.log import logger
    from src.plugins.chiffon_bot.infra.db import connect

    settings = {"engine": "tortoise.backends.sqlite",
                "credentials": {"file_path": str(tmp_path / "blank-titles.sqlite3")}}
    warnings = []
    monkeypatch.setattr(logger, "warning", warnings.append)
    invalid_titles = ((102, ""), (106, "\ufdfa" * 20))
    valid_titles = ((101, "ＦＬＯＷＥＲ"), (103, " \t\u3000"), (104, "Bad\nTitle"),
                    (105, "Bad\u200bTitle"), (1422, "\u3000"))
    valid_aliases = ("🍥\u200b", "(ﾟ∀ﾟ)\u200b", "👑\r\n🔴", "\u200bhop", "Ａｌｉａｓ", "ｶﾞ")
    invalid_aliases = ("\ufdfa" * 20,)
    try:
        await connect.init(db_settings=settings)
        for model, alias_model in ((MaiSong, MaiSongAlias), (ChuniSong, ChuniSongAlias)):
            for song_id, title in (*valid_titles, *invalid_titles):
                song = await model.create(id=song_id, title=title, artist="legacy artist")
                await alias_model.create(song=song, alias=f"legacy-{song_id}")
            for text in (*valid_aliases, *invalid_aliases):
                await alias_model.create(song_id=101, alias=text)
        await connect.close()

        await connect.init(db_settings=settings)
        store = TortoiseCatalogStore(enable_aliases=True)
        first_ids = {}
        for game in ("maimai", "chunithm"):
            first_ids[game] = await store.resolve_reference(game, "101", provider="catalog", namespace="native")
            assert first_ids[game] is not None
            for song_id, _ in invalid_titles:
                assert not await store.resolve_reference(game, str(song_id), provider="catalog", namespace="native")
            aliases = (await store.native_aliases(game))[101]
            assert "legacy-101" in aliases
            assert not set(aliases) & set(invalid_aliases)
            assert {"🍥\u200b", "(\u309a∀\u309a)\u200b", "👑\r\n🔴", "\u200bhop", "Alias", "ガ"} <= set(aliases)
            assert (await store.get_song_by_id(game, first_ids[game])).title == "FLOWER"
            space_id = await store.resolve_reference(game, "1422", provider="catalog", namespace="native")
            assert (await store.get_song_by_id(game, space_id)).title == " "
            from arcade_helper.aliases import AliasService
            assert (await AliasService(store).search_all("1422", game_code=game)).candidates[0].game_song_id == space_id
            assert any(game in message and "102" in message and "106" in message for message in warnings)

        reports = await migrate_catalog_identities(store=store)  # Preview must report skipped IDs, too.
        for game, report in reports.items():
            assert len(report.invalid) == len(invalid_titles) + len(invalid_aliases)
            for song_id, _ in invalid_titles:
                assert any(f"{game}:{song_id}:" in issue for issue in report.invalid)
            assert sum(f"{game}:101:" in issue for issue in report.invalid) == len(invalid_aliases)

        await connect.close()
        await connect.init(db_settings=settings)
        for game in first_ids:
            assert await store.resolve_reference(game, "101", provider="catalog", namespace="native") == first_ids[game]
        for model, alias_model in ((MaiSong, MaiSongAlias), (ChuniSong, ChuniSongAlias)):
            assert await model.all().count() == len(valid_titles) + len(invalid_titles)
            for song_id, title in (*valid_titles, *invalid_titles):
                assert (await model.get(id=song_id)).title == title
            assert set(await alias_model.filter(song_id=101).values_list("alias", flat=True)) == {"legacy-101", *valid_aliases, *invalid_aliases}
            assert await alias_model.all().count() == len(valid_titles) + len(invalid_titles) + len(valid_aliases) + len(invalid_aliases)

        from arcade_helper.aliases import AliasService
        service = AliasService(store, policy=lambda actor, action, game: actor in {1, 2})
        request = await service.submit(actor_id=1, operation="ADD_ALIAS", idempotency_key="width",
                                       payload={"game_song_id": first_ids["maimai"], "text": "Ｃｏｍｍｕｎｉｔｙ\u200b"})
        assert (await service.get_request(request, actor_id=1))["payload"]["text"] == "Community\u200b"
        await service.review(request, actor_id=2, approve=True, expected_version=1, reason="验证全半角")
        assert (await service.resolve_alias("Ｃｏｍｍｕｎｉｔｙ\u200b", game_code="maimai")).candidates
        assert "Community\u200b" in (await store.native_aliases("maimai"))[101]
        for index, text in enumerate((*invalid_aliases, "x" * 257)):
            with pytest.raises(ValueError):
                await service.submit(actor_id=1, operation="ADD_ALIAS", idempotency_key=f"invalid-{index}",
                                     payload={"game_song_id": first_ids["maimai"], "text": text})
    finally:
        await connect.close()


async def test_remote_sync_normalizes_titles_and_aliases_and_preserves_partial_sources(
    seeded_song_db, monkeypatch
):
    from arcade_helper.aliases import AliasObservation
    from arcade_helper.catalog.service import CatalogFetchResult
    from arcade_helper.games.maimai.schemas import MaiSongData
    from arcade_helper.storage.tortoise import MaiSong
    from src.plugins.chiffon_bot.integrations.lxns.client import lxns_client as client
    from src.plugins.chiffon_bot.integrations.lxns.plugin_data import plugin_data
    from src.plugins.chiffon_bot.domains.maimai.maimai_adapter import get_maimai_adapter

    def native(song_id, title, text):
        return MaiSongData(id=song_id, title=title, artist="test",
                           alias_observations=[AliasObservation(source_key="lxns:maimai", text=text)],
                           alias_complete_sources=["lxns:maimai"])

    await client.data.catalog.sync_songs("maimai", {MAI_SONG_ID: native(MAI_SONG_ID, MAI_SONG_TITLE, "keep-me")})
    fetched = {MAI_SONG_ID: native(MAI_SONG_ID, "", "invalid-title"),
               1422: native(1422, "\u3000", "👑\r\n🔴"),
               9999: native(9999, "ＦＬＯＷＥＲ", "Ａｌｉａｓ\u200b")}

    async def fetch(*args, **kwargs):
        return CatalogFetchResult("maimai", fetched, "fixture", data_version=123)

    monkeypatch.setattr(client.data.catalog, "fetch_game_raw_data", fetch)
    assert await client.catalog._sync_adapter_from_remote(get_maimai_adapter())
    assert plugin_data.mai_song_index[1422] == " "
    assert plugin_data.mai_song_index[9999] == "FLOWER"
    assert plugin_data.mai_song_index[MAI_SONG_ID] == MAI_SONG_TITLE
    assert (await MaiSong.get(id=1422)).title == " "
    assert (await MaiSong.get(id=9999)).title == "FLOWER"
    assert (await MaiSong.get(id=MAI_SONG_ID)).title == MAI_SONG_TITLE
    assert "keep-me" in (await client.identities.native_aliases("maimai"))[MAI_SONG_ID]
    report = await client.identities.get_import("maimai", provider="catalog", namespace="native")
    assert len(report["invalid"]) == 1
    assert (await client.catalog.search_song("maimai", "Ａｌｉａｓ\u200b"))[0].song_id == 9999
    assert (await client.catalog.search_song("maimai", "1422"))[0].song_id == 1422
    assert "👑\r\n🔴" in (await client.identities.native_aliases("maimai"))[1422]

    fetched = {MAI_SONG_ID: native(MAI_SONG_ID, "", "invalid-title")}
    revision = await client.identities.get_revision()
    assert not (await client.data.catalog.sync_game_from_remote("maimai")).ok
    assert await client.identities.get_revision() == revision
    assert (await MaiSong.get(id=MAI_SONG_ID)).title == MAI_SONG_TITLE

    # Generic catalogs use the same normalization, including the space title.
    report = await client.identities.import_arcade_catalog("sdvx", {"songs": [
        {"title": "ＦＬＯＷＥＲ", "artist": "test", "sheets": []},
        {"title": "\u3000", "artist": "test", "sheets": []},
    ]})
    assert not report.invalid
    assert {song.title for song in (await client.identities.load_all_songs("sdvx")).values()} == {"FLOWER", " "}

    # Simulate an existing pre-normalization generic reference and verify continuity.
    from arcade_helper.catalog.importer import content_key
    from arcade_helper.storage.tortoise.catalog_models import GameSong, MusicWork, SongReference
    ref = await SongReference.filter(game_code="sdvx", payload__isnull=False).exclude(game_song__title=" ").first()
    original_id = ref.game_song_id
    ref.identity_material["title"] = "ＦＬＯＷＥＲ"
    ref.external_key = content_key(ref.identity_material)
    ref.reference_key = content_key([ref.provider, ref.namespace, "sdvx", "derived", ref.external_key])
    ref.payload["title"] = "ＦＬＯＷＥＲ"
    await ref.save()
    await GameSong.filter(id=original_id).update(title="ＦＬＯＷＥＲ", catalog_payload=ref.payload)
    song = await GameSong.get(id=original_id)
    await MusicWork.filter(id=song.work_id).update(display_title="ＦＬＯＷＥＲ")
    report = await client.identities.import_arcade_catalog("sdvx", {"songs": [
        {"title": "ＦＬＯＷＥＲ", "artist": "test", "sheets": []},
        {"title": "\u3000", "artist": "test", "sheets": []},
    ]})
    assert not report.pending and report.withdrawn == 0
    assert (await client.identities.get_song_by_id("sdvx", original_id)).title == "FLOWER"
    assert (await MusicWork.get(id=song.work_id)).display_title == "FLOWER"
    assert await GameSong.filter(game_code="sdvx").count() == 2
