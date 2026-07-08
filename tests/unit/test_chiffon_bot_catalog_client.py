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

    async def fake_sync() -> None:
        await release.wait()

    catalog.sync_song_data_from_remote = fake_sync  # type: ignore[method-assign]

    assert catalog.start_background_refresh() is True
    assert catalog.start_background_refresh() is False

    release.set()
    assert catalog._refresh_task is not None
    await catalog._refresh_task
    await asyncio.sleep(0)

    assert catalog._refresh_task is None


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
async def test_bot_catalog_search_uses_accepted_alias_overlay(
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

    assert accepted
    assert accepted[0].song_id == 1001
    assert not pending
    assert not rejected


@pytest.mark.asyncio
async def test_bot_catalog_search_uses_embedding_fallback(
    loaded_chiffon_bot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.plugins.chiffon_bot.integrations.lxns.catalog as catalog_module
    from src.plugins.chiffon_bot.integrations.lxns.catalog import BotCatalogClient

    class _Service:
        async def search_song(self, game_code: str, query: str | int):
            return []

        async def get_song_by_id(self, game_code: str, song_id: int):
            return None

        async def load_all_songs(self, game_code: str):
            return {}

        async def load_song_index(self, game_code: str) -> dict[int, str]:
            return {}

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

    async def fake_embedding(catalog, game_code: str, query: str):
        return ["embedding-result"]

    monkeypatch.setattr(catalog_module, "search_song_by_embedding", fake_embedding)

    catalog = BotCatalogClient(
        _Data(),  # type: ignore[arg-type]
        song_store=object(),  # type: ignore[arg-type]
        logger=_Logger(),
        auto_sync_enabled=False,
    )

    assert await catalog.search_song("maimai", "semantic miss") == ["embedding-result"]


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

    class _Search:
        async def search_song(self, query: str | int, *, game_code: str):
            return bm25_results

    class _Data:
        catalog = object()

    async def fake_embedding(catalog, game_code: str, query: str, **kwargs):
        assert kwargs == {"threshold": 55.0, "min_margin": 4.0}
        return embedding_results

    monkeypatch.setattr(catalog_module, "search_song_by_embedding", fake_embedding)

    catalog = BotCatalogClient(
        _Data(),  # type: ignore[arg-type]
        song_store=object(),  # type: ignore[arg-type]
        logger=_Logger(),
        auto_sync_enabled=False,
    )
    catalog.search = _Search()  # type: ignore[assignment]

    assert await catalog.search_song("popn", "semantic miss") == embedding_results


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

    class _Search:
        async def search_song(self, query: str | int, *, game_code: str):
            return bm25_results

    class _Data:
        catalog = object()

    async def fake_reranker(catalog, game_code: str, query: str, results):
        assert results == bm25_results
        return [bm25_results[1]]

    async def fake_embedding(*_args, **_kwargs):
        raise AssertionError("embedding should not run after reranker hit")

    monkeypatch.setattr(catalog_module, "rerank_song_results", fake_reranker)
    monkeypatch.setattr(catalog_module, "search_song_by_embedding", fake_embedding)

    catalog = BotCatalogClient(
        _Data(),  # type: ignore[arg-type]
        song_store=object(),  # type: ignore[arg-type]
        logger=_Logger(),
        auto_sync_enabled=False,
    )
    catalog.search = _Search()  # type: ignore[assignment]

    assert await catalog.search_song("popn", "semantic miss") == [bm25_results[1]]


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
