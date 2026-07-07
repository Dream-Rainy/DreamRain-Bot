from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from arcade_helper.core.song import SongData


@pytest.mark.asyncio
async def test_ollama_embed_provider_parses_api_embed_response() -> None:
    from src.plugins.chiffon_bot.shared.search.embedding_provider import embed_texts

    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        assert payload["model"] == "embeddinggemma"
        assert payload["input"] == ["alpha", "beta"]
        return httpx.Response(200, json={"embeddings": [[1, 0], [0, 1]]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        vectors = await embed_texts(
            ["alpha", "beta"],
            endpoint="http://ollama.test/api/embed",
            model="embeddinggemma",
            client=client,
        )

    assert vectors == [[1.0, 0.0], [0.0, 1.0]]


@pytest.mark.asyncio
async def test_embedding_cache_rebuild_and_search(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from arcade_helper.search import MatchType
    from src.plugins.chiffon_bot.shared.search import embedding_cache

    class _Catalog:
        def __init__(self) -> None:
            self.songs = {
                1005: SongData(id=1005, title="Blue Noise", artist="Sakuzyo"),
                1006: SongData(id=1006, title="Red Noise", artist="Other"),
            }

        async def load_all_songs(self, game_code: str) -> dict[int, SongData]:
            return self.songs

        async def load_alias_records(self, game_code: str) -> list[tuple[int, str]]:
            return [(1005, "青いノイズ")]

        async def get_song_by_id(self, game_code: str, song_id: int) -> Any:
            return self.songs.get(song_id)

    async def rebuild_embedder(texts: list[str]) -> list[list[float]]:
        assert "Blue Noise" in texts[0]
        assert "青いノイズ" in texts[0]
        return [[1, 0], [0, 1]]

    async def query_embedder(texts: list[str]) -> list[list[float]]:
        assert texts == ["semantic blue"]
        return [[1, 0]]

    path = tmp_path / "embeddings.jsonl"
    monkeypatch.setattr(embedding_cache, "embedding_enabled", lambda: True)
    monkeypatch.setattr(embedding_cache, "embedding_path", lambda: path)
    monkeypatch.setattr(embedding_cache, "embedding_threshold", lambda: 90.0)
    monkeypatch.setattr(embedding_cache, "embedding_model", lambda: "test-model")

    result = await embedding_cache.rebuild_song_embeddings(_Catalog(), "quality", embedder=rebuild_embedder)
    assert result["songs"] == 2
    assert result["model"] == "test-model"
    assert embedding_cache.embedding_status()["songs"] == {"quality": 2}

    results = await embedding_cache.search_song_by_embedding(
        _Catalog(),
        "quality",
        "semantic blue",
        embedder=query_embedder,
    )

    assert results
    assert results[0].song_id == 1005
    assert results[0].match_type is MatchType.EMBEDDING


@pytest.mark.asyncio
async def test_embedding_cache_rebuild_batches_requests(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from src.plugins.chiffon_bot.shared.search import embedding_cache

    songs = {
        song_id: SongData(id=song_id, title=f"Song {song_id}", artist="Artist")
        for song_id in range(1, 6)
    }
    batches: list[list[str]] = []

    async def embedder(texts: list[str]) -> list[list[float]]:
        batches.append(list(texts))
        return [[float(len(batches)), float(index)] for index, _text in enumerate(texts)]

    path = tmp_path / "embeddings.jsonl"
    monkeypatch.setattr(embedding_cache, "_EMBEDDING_REBUILD_BATCH_SIZE", 2)
    monkeypatch.setattr(embedding_cache, "embedding_path", lambda: path)
    monkeypatch.setattr(embedding_cache, "embedding_model", lambda: "test-model")

    result = await embedding_cache.rebuild_song_embeddings_from_songs(
        "quality",
        songs,
        embedder=embedder,
    )

    assert result["songs"] == 5
    assert [len(batch) for batch in batches] == [2, 2, 1]
    assert embedding_cache.embedding_status(path)["songs"] == {"quality": 5}
