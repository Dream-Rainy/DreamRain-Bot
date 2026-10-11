from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from arcade_helper import ArcadeHelperClient
from arcade_helper.core.song import SongData


class _Logger:
    def debug(self, *_args: Any, **_kwargs: Any) -> None:
        pass

    def info(self, *_args: Any, **_kwargs: Any) -> None:
        pass

    def warning(self, *_args: Any, **_kwargs: Any) -> None:
        pass

    def error(self, *_args: Any, **_kwargs: Any) -> None:
        pass


@pytest.mark.asyncio
async def test_cross_game_vector_checks_are_bounded_and_keep_only_unverified_text(loaded_chiffon_bot, monkeypatch):
    from arcade_helper.search import MatchType, SongQueryResult
    from src.plugins.chiffon_bot.integrations.lxns import catalog as module
    catalog = _catalog(loaded_chiffon_bot)
    games = [f"game{i}" for i in range(6)]
    rows = [SongQueryResult(i, "Example", MatchType.BM25, 95, "query", SongData(
                id=i, title="Example", game_code=game, work_id=f"work{i}")) for i, game in enumerate(games)]
    active = peak = 0
    calls = []
    async def skip(*args, **kwargs):
        return None
    async def vectors(catalog, game, query, **kwargs):
        nonlocal active, peak
        calls.append(game)
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        return None if game == games[0] else []
    monkeypatch.setattr(module, "rerank_song_results", skip)
    monkeypatch.setattr(module, "embedding_enabled", lambda: True)
    monkeypatch.setattr(module, "reranker_enabled", lambda: False)
    monkeypatch.setattr(module, "search_song_by_embedding", vectors)
    assert await catalog._validate_results("unsupported query", rows, games) == rows[:1]
    assert peak == 2 and sorted(calls) == games


@pytest.mark.asyncio
async def test_same_work_entries_do_not_trigger_ambiguity_models(loaded_chiffon_bot, monkeypatch):
    from arcade_helper.search import MatchType, SongQueryResult
    from src.plugins.chiffon_bot.integrations.lxns import catalog as module
    catalog = _catalog(loaded_chiffon_bot)
    rows = [SongQueryResult(i, "Example", MatchType.BM25, 95, "query", SongData(
                id=i, title="Example", game_code=game, work_id="confirmed-work")) for i, game in enumerate(("sdvx", "ongeki"))]
    calls = []
    async def forbidden(*args, **kwargs):
        calls.append(args)
        return []
    monkeypatch.setattr(module, "rerank_song_results", forbidden)
    monkeypatch.setattr(module, "search_song_by_embedding", forbidden)
    assert await catalog._validate_results("composer example", rows, ["sdvx", "ongeki"]) == rows
    assert calls == []


@pytest.mark.asyncio
async def test_short_catalog_queries_never_invoke_models(loaded_chiffon_bot, monkeypatch):
    from types import SimpleNamespace
    from src.plugins.chiffon_bot.integrations.lxns import catalog as module
    catalog = _catalog(loaded_chiffon_bot)

    async def no_text(*args, **kwargs):
        return []

    calls = []

    async def forbidden(*args, **kwargs):
        calls.append(args)
        return []

    catalog.search = SimpleNamespace(search_candidates=no_text)
    monkeypatch.setattr(module, "search_song_by_embedding", forbidden)
    monkeypatch.setattr(module, "rerank_song_results", forbidden)
    for query in ("ｔｅｔｏ", "测", "qby", "zzzz"):
        assert await catalog.search_song("sdvx", query) == []
    assert calls == []


@pytest.mark.asyncio
async def test_model_rejection_never_restores_bm25(loaded_chiffon_bot, monkeypatch):
    from arcade_helper.search import MatchType, SongQueryResult
    from src.plugins.chiffon_bot.integrations.lxns import catalog as module
    catalog = _catalog(loaded_chiffon_bot)
    songs = [SongData(id=1, title="First"), SongData(id=2, title="Second")]
    candidates = [SongQueryResult(s.id, s.title, MatchType.BM25, 95, s.title, s) for s in songs]

    async def reject(*args, **kwargs):
        return []

    calls = []
    async def forbidden(*args, **kwargs):
        calls.append(args)
        return candidates

    monkeypatch.setattr(module, "rerank_song_results", reject)
    monkeypatch.setattr(module, "search_song_by_embedding", forbidden)
    assert await catalog._validate_results("unsupported query", candidates, ["sdvx"]) == []
    assert calls == []


@pytest.mark.asyncio
async def test_failed_text_reranker_is_not_called_again_for_novel_vector_candidates(loaded_chiffon_bot, monkeypatch):
    from arcade_helper.search import MatchType, SongQueryResult
    from src.plugins.chiffon_bot.integrations.lxns import catalog as module
    catalog = _catalog(loaded_chiffon_bot)
    rows = [SongQueryResult(i, f"Text {i}", MatchType.BM25, 95, "query", SongData(id=i, title=f"Text {i}")) for i in (1, 2)]
    novel = SongQueryResult(3, "Other work", MatchType.EMBEDDING, 99, "query", SongData(id=3, title="Other work"))
    calls = []
    async def fail(*args):
        calls.append(args)
        raise RuntimeError("offline")
    async def vectors(*args, **kwargs):
        return [novel]
    monkeypatch.setattr(module, "rerank_song_results", fail)
    monkeypatch.setattr(module, "search_song_by_embedding", vectors)
    monkeypatch.setattr(module, "embedding_enabled", lambda: True)
    monkeypatch.setattr(module, "reranker_enabled", lambda: True)
    monkeypatch.setattr(module, "reranker_threshold", lambda: 0.6)
    assert await catalog._validate_results("query words", rows, ["sdvx"]) == []
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("offline", [False, True])
async def test_embedding_rejection_and_failure_are_distinct(loaded_chiffon_bot, monkeypatch, offline):
    from arcade_helper.search import MatchType, SongQueryResult
    from src.plugins.chiffon_bot.integrations.lxns import catalog as module
    catalog = _catalog(loaded_chiffon_bot)
    songs = [SongData(id=1, title="First"), SongData(id=2, title="Second")]
    candidates = [SongQueryResult(s.id, s.title, MatchType.BM25, 95, s.title, s) for s in songs]

    async def skipped(*args, **kwargs):
        return None

    async def embedding(*args, **kwargs):
        assert kwargs == {"hydrate": False, "internal_ids": False}
        if offline:
            raise RuntimeError("service offline")
        return []

    monkeypatch.setattr(module, "embedding_enabled", lambda: True)
    monkeypatch.setattr(module, "rerank_song_results", skipped)
    monkeypatch.setattr(module, "search_song_by_embedding", embedding)
    assert await catalog._validate_results("query words", candidates, ["sdvx"]) == (candidates if offline else [])


@pytest.mark.asyncio
async def test_missing_embedding_cache_preserves_validated_text(loaded_chiffon_bot, monkeypatch, tmp_path):
    from arcade_helper.search import MatchType, SongQueryResult
    from src.plugins.chiffon_bot.integrations.lxns import catalog as module
    from src.plugins.chiffon_bot.shared.search import embedding_cache as cache
    catalog = _catalog(loaded_chiffon_bot)
    songs = [SongData(id=1, title="First"), SongData(id=2, title="Second")]
    candidates = [SongQueryResult(s.id, s.title, MatchType.BM25, 95, s.title, s) for s in songs]

    async def skipped(*args, **kwargs):
        return None

    async def revision():
        return 1

    async def embedding(*args, **kwargs):
        return await cache.search_song_by_embedding(*args, path=tmp_path / "absent.jsonl", **kwargs)

    monkeypatch.setattr(catalog, "get_revision", revision)
    monkeypatch.setattr(module, "embedding_enabled", lambda: True)
    monkeypatch.setattr(cache, "embedding_enabled", lambda: True)
    monkeypatch.setattr(module, "rerank_song_results", skipped)
    monkeypatch.setattr(module, "search_song_by_embedding", embedding)
    assert await catalog._validate_results("query words", candidates, ["sdvx"]) == candidates


@pytest.mark.asyncio
@pytest.mark.parametrize("query_vector", [[1.0, 0.0], [0.0, 1.0]])
async def test_embedding_revision_change_invalidates_acceptance_and_rejection(monkeypatch, tmp_path, query_vector):
    from types import SimpleNamespace
    from src.plugins.chiffon_bot.shared.search import embedding_cache as cache

    current_revision = 1

    async def revision():
        return current_revision

    async def song(*args):
        return SongData(id=1, title="First")

    async def embed(texts):
        nonlocal current_revision
        current_revision = 2
        return [query_vector]

    path = tmp_path / "embeddings.jsonl"
    path.write_text(json.dumps({"game": "sdvx", "song_id": 1, "vector": [1.0, 0.0],
                                "revision": 1, "model": "test", "endpoint": "test"}), encoding="utf-8")
    monkeypatch.setattr(cache, "embedding_enabled", lambda: True)
    monkeypatch.setattr(cache, "embedding_model", lambda: "test")
    monkeypatch.setattr(cache, "embedding_endpoint", lambda: "test")
    catalog = SimpleNamespace(get_revision=revision, get_song_by_id=song)
    assert await cache.search_song_by_embedding(catalog, "sdvx", "query", path=path, embedder=embed, threshold=80) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("threshold", [0.0, 0.6])
async def test_pure_semantic_candidates_require_positive_gate(loaded_chiffon_bot, monkeypatch, threshold):
    from arcade_helper.search import MatchType, SongQueryResult
    from src.plugins.chiffon_bot.integrations.lxns import catalog as module
    catalog = _catalog(loaded_chiffon_bot)
    song = SongData(id=1, title="Example")
    candidates = [SongQueryResult(1, song.title, MatchType.EMBEDDING, 90, "query", song)]
    calls = []

    async def embedding(*args, **kwargs):
        calls.append("embedding")
        return candidates

    async def reject(*args, **kwargs):
        calls.append("reranker")
        return []

    monkeypatch.setattr(module, "embedding_enabled", lambda: True)
    monkeypatch.setattr(module, "reranker_enabled", lambda: True)
    monkeypatch.setattr(module, "reranker_threshold", lambda: threshold)
    monkeypatch.setattr(module, "search_song_by_embedding", embedding)
    monkeypatch.setattr(module, "rerank_song_results", reject)
    assert await catalog._validate_results("unrelated query", [], ["sdvx"]) == []
    assert calls == (["embedding", "reranker"] if threshold else [])


async def _get_json(_url: str, **_kwargs: Any) -> dict[str, Any]:
    return {}


def _catalog(loaded_chiffon_bot):
    from src.plugins.chiffon_bot.integrations.lxns.catalog import BotCatalogClient
    from arcade_helper.storage.tortoise import TortoiseSongStore

    data = ArcadeHelperClient(http_get_json=_get_json)
    return BotCatalogClient(
        data,
        song_store=TortoiseSongStore(logger=_Logger()),
        logger=_Logger(),
        auto_sync_enabled=True,
        auto_sync_interval_seconds=60,
        auto_sync_startup_delay_seconds=0,
        background_refresh_delay_seconds=0,
    )


@pytest.mark.asyncio
async def test_catalog_background_refresh_is_single_flight(loaded_chiffon_bot) -> None:
    catalog = _catalog(loaded_chiffon_bot)
    release = asyncio.Event()

    async def fake_sync() -> str:
        await release.wait()
        return "同步完成"

    catalog.sync_song_data_from_remote = fake_sync  # type: ignore[method-assign]

    assert catalog.start_background_refresh() is True
    assert catalog.start_background_refresh() is False

    release.set()
    assert catalog._refresh_task is not None
    await catalog._refresh_task
    await asyncio.sleep(0)

    assert catalog._refresh_task is None
    assert await catalog.wait_for_refresh() == "同步完成"


@pytest.mark.asyncio
async def test_text_prewarm_shares_snapshot_without_embeddings_and_refreshes_generation(
    loaded_chiffon_bot, monkeypatch,
):
    from types import SimpleNamespace
    from src.plugins.chiffon_bot.integrations.lxns import catalog as module
    catalog = _catalog(loaded_chiffon_bot)
    identities = SimpleNamespace(_db=object(), enable_aliases=False)
    catalog.service.identities = identities
    state = {"revision": 1, "title": "First Song"}
    reads = []

    async def revision():
        return state["revision"]

    async def songs(game):
        reads.append(game)
        return {1: SongData(id=1, title=state["title"], aliases=["loaded alias"])}

    async def forbidden(*args):
        raise AssertionError("populated aliases or disabled embeddings were loaded again")

    monkeypatch.setattr(module, "embedding_enabled", lambda: False)
    monkeypatch.setattr(catalog, "get_revision", revision)
    monkeypatch.setattr(catalog, "_load_search_songs", songs)
    monkeypatch.setattr(catalog, "load_alias_records", forbidden)
    monkeypatch.setattr(catalog, "rebuild_search_embeddings", forbidden)
    monkeypatch.setattr(catalog, "_domain_adapters", lambda: [SimpleNamespace(game_code="sdvx")])
    await catalog._refresh_search_caches()
    shared, aliases = await catalog.load_embedding_inputs("sdvx")
    assert shared[1].title == "First Song" and aliases == [(1, "loaded alias")]
    await catalog._refresh_search_caches()
    assert reads == ["sdvx"]
    state.update(revision=2, title="New Song")
    await catalog._refresh_search_caches()
    assert catalog.search._cache.indexes[("sdvx", None)].index == {1: "New Song"}
    identities._db = object()  # Same revision on a different connection must reload.
    state["title"] = "Other Database"
    await catalog._refresh_search_caches()
    assert catalog.search._cache.indexes[("sdvx", None)].index == {1: "Other Database"}
    assert reads == ["sdvx"] * 3
    await catalog.stop_auto_sync()


@pytest.mark.asyncio
async def test_background_embeddings_retry_update_and_cancel_without_blocking_startup(loaded_chiffon_bot, monkeypatch, tmp_path):
    from src.plugins.chiffon_bot.shared.search import embedding_cache as cache
    from src.plugins.chiffon_bot.integrations.lxns import catalog as module
    catalog = _catalog(loaded_chiffon_bot)
    path = tmp_path / 'vectors.jsonl'
    binary = cache._game_path(path, 'maimai')
    state = {'revision': 1, 'alias': 'first', 'fail': True, 'block': False}
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []
    preparations = []
    async def revision():
        return state['revision']
    async def songs(game):
        preparations.append((game, state['revision']))
        return {1: SongData(id=1, title='Song')}
    async def aliases(game):
        return [(1, state['alias'])]
    async def infer(texts):
        calls.append(texts)
        if state['fail']:
            state['fail'] = False
            raise RuntimeError('offline')
        if state['block']:
            entered.set()
            await release.wait()
        return [[1.0, 0.0] for _ in texts]
    async def rebuild(game):
        return await cache.rebuild_song_embeddings(catalog, game, path=path, embedder=infer)
    async def load():
        return True, 'loaded'
    monkeypatch.setattr(module, 'embedding_enabled', lambda: True)
    monkeypatch.setattr(catalog, '_domain_adapters', lambda: [type('Adapter', (), {'game_code': 'maimai'})()])
    monkeypatch.setattr(catalog, 'get_revision', revision)
    monkeypatch.setattr(catalog, '_load_search_songs', songs)
    monkeypatch.setattr(catalog, 'load_alias_records', aliases)
    monkeypatch.setattr(catalog, 'rebuild_search_embeddings', rebuild)
    await catalog._refresh_search_caches()
    assert not binary.exists() and not catalog._embedding_generations
    await catalog._refresh_search_caches()
    assert binary.exists() and len(calls) == 2
    assert preparations == [('maimai', 1)]
    await catalog._refresh_search_caches()
    assert len(calls) == 2
    state.update(revision=2, alias='updated')
    await catalog._refresh_search_caches()
    rows, _ = cache._song_index(path, 'maimai')
    assert calls[-1] == ['Song | updated'] and rows[0]['revision'] == 2
    assert preparations == [('maimai', 1), ('maimai', 2)]

    before = binary.read_bytes()
    state.update(revision=3, alias='blocking', block=True)
    monkeypatch.setattr(catalog, 'load_song_data_from_db', load)
    monkeypatch.setattr(catalog, 'start_background_refresh', lambda: False)
    try:
        assert (await catalog.refresh_song_data())[0]
        await asyncio.wait_for(entered.wait(), 3)
        assert catalog._cache_task is not None and not catalog._cache_task.done()
    finally:
        await catalog.stop_auto_sync()
    assert catalog._cache_task is None and binary.read_bytes() == before


@pytest.mark.asyncio
async def test_catalog_sync_reports_partial_failure(loaded_chiffon_bot, monkeypatch: pytest.MonkeyPatch) -> None:
    catalog = _catalog(loaded_chiffon_bot)
    adapters = [
        type("Adapter", (), {"display_name": "maimai", "game_code": "maimai"})(),
        type("Adapter", (), {"display_name": "CHUNITHM", "game_code": "chunithm"})(),
    ]

    monkeypatch.setattr(catalog, "_domain_adapters", lambda: adapters)

    async def fake_sync(adapter) -> bool:
        return adapter.game_code == "maimai"

    monkeypatch.setattr(catalog, "_sync_adapter_from_remote", fake_sync)

    assert await catalog.sync_song_data_from_remote() == "后台同步完成：成功 maimai；失败 CHUNITHM"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["success", "failed", "already_running"])
async def test_background_sync_handles_omitted_songs_and_preserves_local_data_on_failure(loaded_chiffon_bot, monkeypatch, status):
    from types import SimpleNamespace
    from src.plugins.chiffon_bot.integrations.lxns.plugin_data import plugin_data
    from src.plugins.chiffon_bot.shared.game import get_domain_adapter

    catalog = _catalog(loaded_chiffon_bot)
    adapter = get_domain_adapter("maimai")
    old_index, old_store = {99: "Old"}, {99: object()}
    monkeypatch.setattr(plugin_data, adapter.song_index_attr, old_index)
    monkeypatch.setattr(plugin_data, adapter.song_store_attr, old_store)
    monkeypatch.setattr(plugin_data, "data_version", 3)
    catalog._embedding_generations["maimai"] = (1, "old")
    calls = []
    async def sync(game, *, current_data_version, include_songs):
        assert game == "maimai" and current_data_version == 3 and include_songs is False
        return SimpleNamespace(ok=status == "success", status=status, songs=None, data_version=7, error=RuntimeError("offline"))
    async def index(game):
        calls.append("index")
        return {101: "New"}
    monkeypatch.setattr(catalog.service, "sync_game_from_remote", sync)
    monkeypatch.setattr(catalog.service, "load_song_index", index)
    monkeypatch.setattr(adapter, "clear_image_cache", lambda: calls.append("images"))
    monkeypatch.setattr(catalog, "invalidate_alias_cache", lambda game: calls.append("aliases"))
    assert await catalog._sync_adapter_from_remote(adapter) is (status == "success")
    if status == "success":
        assert getattr(plugin_data, adapter.song_index_attr) == {101: "New"}
        assert getattr(plugin_data, adapter.song_store_attr) == {} and plugin_data.data_version == 7
        assert calls == ["index", "images", "aliases"] and "maimai" not in catalog._embedding_generations
    else:
        assert getattr(plugin_data, adapter.song_index_attr) is old_index
        assert getattr(plugin_data, adapter.song_store_attr) is old_store and plugin_data.data_version == 3
        assert not calls and "maimai" in catalog._embedding_generations


@pytest.mark.asyncio
async def test_manual_refresh_starts_auto_sync(loaded_chiffon_bot, monkeypatch: pytest.MonkeyPatch) -> None:
    catalog = _catalog(loaded_chiffon_bot)
    calls: list[str] = []

    async def fake_load() -> tuple[bool, str]:
        return True, "loaded"

    monkeypatch.setattr(catalog, "load_song_data_from_db", fake_load)
    monkeypatch.setattr(catalog, "start_background_refresh", lambda: True)
    monkeypatch.setattr(catalog, "start_auto_sync", lambda: calls.append("auto") or True)

    assert await catalog.refresh_song_data(manual=True) == (True, "loaded；已启动后台同步")
    assert calls == ["auto"]


def test_lxns_client_exposes_catalog(loaded_chiffon_bot) -> None:
    from src.plugins.chiffon_bot.integrations.lxns.client import lxns_client

    assert lxns_client.catalog.data is lxns_client.data
    assert lxns_client.catalog.service is lxns_client.data.catalog


def test_admin_search_formats_musicbrainz_score(loaded_chiffon_bot) -> None:
    from src.plugins.chiffon_bot.app.commands.admin import _format_candidate

    text = _format_candidate({
        "line": 1,
        "game": "quality",
        "alias": "青いノイズ",
        "song_id": 1005,
        "title": "Blue Noise",
        "source": "musicbrainz",
        "status": "pending",
        "evidence": {"musicbrainz_score": 98},
    })

    assert "score=98" in text
    assert "type=musicbrainz" in text


@pytest.mark.asyncio
async def test_bot_catalog_query_delegates_to_data_catalog(loaded_chiffon_bot, monkeypatch: pytest.MonkeyPatch) -> None:
    catalog = _catalog(loaded_chiffon_bot)
    calls: list[tuple[str, int]] = []

    async def fake_get_song_by_id(game_code: str, song_id: int):
        calls.append((game_code, song_id))
        return {"id": song_id}

    monkeypatch.setattr(catalog.service, "get_song_by_id", fake_get_song_by_id)

    assert await catalog.get_song_by_id("maimai", 123) == {"id": 123}
    assert calls == [("maimai", 123)]


@pytest.mark.asyncio
async def test_bot_catalog_db_game_value_error_is_not_arcade_fallback(
    loaded_chiffon_bot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = _catalog(loaded_chiffon_bot)

    async def fake_get_song_by_id(game_code: str, song_id: int):
        raise ValueError("db catalog broke")

    monkeypatch.setattr(catalog.service, "get_song_by_id", fake_get_song_by_id)

    with pytest.raises(ValueError, match="db catalog broke"):
        await catalog.get_song_by_id("maimai", 123)


@pytest.mark.asyncio
async def test_bot_catalog_does_not_overlay_legacy_review_history(
    loaded_chiffon_bot,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from src.plugins.chiffon_bot.integrations.lxns.catalog import BotCatalogClient

    class _Service:
        def __init__(self) -> None:
            self.songs = {
                1001: SongData(id=1001, title="Overlay Target", artist="test"),
            }

        async def get_song_by_id(self, game_code: str, song_id: int):
            return self.songs.get(song_id)

        async def load_all_songs(self, game_code: str):
            return self.songs

        async def load_song_index(self, game_code: str) -> dict[int, str]:
            return {song_id: song.title for song_id, song in self.songs.items()}

        async def query_alias_exact(self, game_code: str, alias_lower: str) -> list[tuple[int, str]]:
            return []

        async def load_alias_records(self, game_code: str) -> list[tuple[int, str]]:
            return []

        async def get_song_aliases_for_song_id(self, game_code: str, song_id: int) -> list[str]:
            return []

        async def get_song_with_difficulty(
            self,
            game_code: str,
            song_id: int,
            song_type: str = "standard",
            level_index: int = 3,
        ) -> dict | None:
            return None

        def invalidate_search_cache(self, game_code: str) -> None:
            pass

    class _Data:
        def __init__(self) -> None:
            self.catalog = _Service()

    history_path = tmp_path / "history.jsonl"
    rows = [
        {
            "game": "maimai",
            "query": "accepted-alias",
            "alias_candidate": {
                "alias": "accepted-alias",
                "song_id": 1001,
                "title": "Overlay Target",
                "status": "accepted",
            },
        },
        {
            "game": "maimai",
            "query": "pending-alias",
            "alias_candidate": {
                "alias": "pending-alias",
                "song_id": 1001,
                "title": "Overlay Target",
                "status": "pending",
            },
        },
        {
            "game": "maimai",
            "query": "rejected-alias",
            "alias_candidate": {
                "alias": "rejected-alias",
                "song_id": 1001,
                "title": "Overlay Target",
                "status": "rejected",
            },
        },
    ]
    history_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SONG_SEARCH_AUDIT_PATH", str(history_path))

    catalog = BotCatalogClient(
        _Data(),  # type: ignore[arg-type]
        song_store=object(),  # type: ignore[arg-type]
        logger=_Logger(),
        auto_sync_enabled=False,
    )

    accepted = await catalog.search_song("maimai", "accepted-alias")
    pending = await catalog.search_song("maimai", "pending-alias")
    rejected = await catalog.search_song("maimai", "rejected-alias")

    assert not accepted
    assert not pending
    assert not rejected


@pytest.mark.asyncio
async def test_bot_catalog_search_uses_embedding_fallback(
    loaded_chiffon_bot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.plugins.chiffon_bot.integrations.lxns.catalog as catalog_module
    from src.plugins.chiffon_bot.integrations.lxns.catalog import BotCatalogClient
    from arcade_helper.search import MatchType, SongQueryResult

    song = SongData(id=1005, title="Blue Noise", aliases=[])
    semantic = [SongQueryResult(song.id, song.title, MatchType.EMBEDDING, 90, "query", song)]

    async def fake_embedding(catalog, game_code: str, query: str, **kwargs):
        return semantic

    async def confirm(catalog, game_code, query, candidates):
        assert candidates == semantic
        return candidates

    monkeypatch.setattr(catalog_module, "search_song_by_embedding", fake_embedding)
    monkeypatch.setattr(catalog_module, "embedding_enabled", lambda: True)
    monkeypatch.setattr(catalog_module, "reranker_enabled", lambda: True)
    monkeypatch.setattr(catalog_module, "reranker_threshold", lambda: 0.6)
    monkeypatch.setattr(catalog_module, "rerank_song_results", confirm)

    catalog = _catalog(loaded_chiffon_bot)

    assert await catalog._validate_results("semantic miss", [], ["maimai"]) == semantic


@pytest.mark.asyncio
async def test_bot_catalog_search_defers_uncertain_bm25_to_embedding(
    loaded_chiffon_bot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.plugins.chiffon_bot.integrations.lxns.catalog as catalog_module
    from arcade_helper.search import MatchType, SongQueryResult
    from src.plugins.chiffon_bot.integrations.lxns.catalog import BotCatalogClient

    blue_noise = SongData(id=1005, title="Blue Noise", artist="Sakuzyo")
    red_noise = SongData(id=1006, title="Red Noise", artist="Other")
    bm25_results = [
        SongQueryResult(1005, "Blue Noise", MatchType.BM25, 95.0, "Blue Noise", blue_noise),
        SongQueryResult(1006, "Red Noise", MatchType.BM25, 94.0, "Red Noise", red_noise),
    ]
    embedding_results = [
        SongQueryResult(1006, "Red Noise", MatchType.EMBEDDING, 96.0, "semantic miss", red_noise),
    ]

    async def fake_embedding(catalog, game_code: str, query: str, **kwargs):
        assert kwargs == {"hydrate": False, "internal_ids": False}
        return embedding_results

    monkeypatch.setattr(catalog_module, "search_song_by_embedding", fake_embedding)
    monkeypatch.setattr(catalog_module, "embedding_enabled", lambda: True)
    monkeypatch.setattr(catalog_module, "reranker_enabled", lambda: False)

    catalog = _catalog(loaded_chiffon_bot)

    assert await catalog._validate_results("semantic miss", bm25_results, ["popn"]) == embedding_results


@pytest.mark.asyncio
async def test_bot_catalog_search_defers_uncertain_bm25_to_reranker(
    loaded_chiffon_bot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.plugins.chiffon_bot.integrations.lxns.catalog as catalog_module
    from arcade_helper.search import MatchType, SongQueryResult
    from src.plugins.chiffon_bot.integrations.lxns.catalog import BotCatalogClient

    blue_noise = SongData(id=1005, title="Blue Noise", artist="Sakuzyo")
    red_noise = SongData(id=1006, title="Red Noise", artist="Other")
    bm25_results = [
        SongQueryResult(1005, "Blue Noise", MatchType.BM25, 95.0, "Blue Noise", blue_noise),
        SongQueryResult(1006, "Red Noise", MatchType.BM25, 94.0, "Red Noise", red_noise),
    ]

    async def fake_reranker(catalog, game_code: str, query: str, results):
        assert results == bm25_results
        return [bm25_results[1]]

    async def fake_embedding(*_args, **_kwargs):
        raise AssertionError("embedding should not run after reranker hit")

    monkeypatch.setattr(catalog_module, "rerank_song_results", fake_reranker)
    monkeypatch.setattr(catalog_module, "search_song_by_embedding", fake_embedding)

    catalog = _catalog(loaded_chiffon_bot)

    assert await catalog._validate_results("semantic miss", bm25_results, ["popn"]) == [bm25_results[1]]


@pytest.mark.asyncio
async def test_rebuild_search_embeddings_uses_arcade_catalog_for_generic_game(
    loaded_chiffon_bot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.plugins.chiffon_bot.integrations.lxns.catalog as catalog_module
    from src.plugins.chiffon_bot.integrations.lxns.catalog import BotCatalogClient

    class _ArcadeSongs:
        async def catalog(self, game_code: str):
            return {
                3001: SongData(id=3001, title="Generic Song", artist="Artist", aliases=["Alias"]),
            }

    class _Service:
        def __init__(self) -> None:
            self.arcade_songs = _ArcadeSongs()

        async def get_song_by_id(self, game_code: str, song_id: int):
            raise ValueError("Unsupported game_code")

        async def load_all_songs(self, game_code: str):
            raise ValueError("Unsupported game_code")

        async def load_song_index(self, game_code: str) -> dict[int, str]:
            raise ValueError("Unsupported game_code")

        async def query_alias_exact(self, game_code: str, alias_lower: str) -> list[tuple[int, str]]:
            raise ValueError("Unsupported game_code")

        async def load_alias_records(self, game_code: str) -> list[tuple[int, str]]:
            raise ValueError("Unsupported game_code")

        async def get_song_aliases_for_song_id(self, game_code: str, song_id: int) -> list[str]:
            raise ValueError("Unsupported game_code")

        async def get_song_with_difficulty(
            self,
            game_code: str,
            song_id: int,
            song_type: str = "standard",
            level_index: int = 3,
        ) -> dict | None:
            return None

        def invalidate_search_cache(self, game_code: str) -> None:
            pass

    class _Data:
        def __init__(self) -> None:
            self.catalog = _Service()

    async def fake_rebuild(game_code, songs, *, alias_records=None, **_kwargs):
        assert game_code == "sdvx"
        assert list(songs) == [3001]
        assert alias_records == [(3001, "Alias")]
        return {"game": game_code, "songs": len(songs), "path": "test", "model": "test-model"}

    monkeypatch.setattr(catalog_module, "rebuild_song_embeddings_from_songs", fake_rebuild)

    catalog = BotCatalogClient(
        _Data(),  # type: ignore[arg-type]
        song_store=object(),  # type: ignore[arg-type]
        logger=_Logger(),
        auto_sync_enabled=False,
    )

    assert await catalog.rebuild_search_embeddings("sdvx") == {
        "game": "sdvx",
        "songs": 1,
        "path": "test",
        "model": "test-model",
    }
