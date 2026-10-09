from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from arcade_helper.core.song import SongData


@pytest.mark.asyncio
async def test_legacy_vectors_migrate_without_inference_and_binary_search_keeps_scores(monkeypatch, tmp_path):
    import numpy as np
    from src.plugins.chiffon_bot.shared.search import embedding_cache as cache
    path = tmp_path / 'legacy.jsonl'
    monkeypatch.setattr(cache, 'embedding_enabled', lambda: True)
    monkeypatch.setattr(cache, 'embedding_model', lambda: 'model')
    monkeypatch.setattr(cache, 'embedding_endpoint', lambda: 'endpoint')
    vectors = [[3.0, 4.0], [4.0, 3.0]]
    rows = [{'game': 'sdvx', 'song_id': i + 1, 'title': f'Song {i}', 'text': f'Song {i}',
             'vector': vector, 'model': 'model', 'endpoint': 'endpoint', 'revision': 1}
            for i, vector in enumerate(vectors)]
    path.write_text('\n'.join(json.dumps(row) for row in rows), encoding='utf-8')
    original = path.read_bytes()
    songs = {row['song_id']: SongData(id=row['song_id'], title=row['title']) for row in rows}
    async def no_inference(texts):
        raise AssertionError('Migration must reuse existing song embeddings')
    await cache.rebuild_song_embeddings_from_songs('sdvx', songs, path=path, embedder=no_inference, revision=2)
    cache._INDEX_CACHE.clear()  # A restart must load the binary independently of JSONL.
    def no_legacy_read(path):
        raise AssertionError('Binary query must not read the legacy JSONL')
    monkeypatch.setattr(cache, '_iter_lines', no_legacy_read)
    metadata, matrix = cache._song_index(path, 'sdvx')
    assert matrix.dtype == np.float32 and matrix.nbytes == 16
    assert all('vector' not in row for row in metadata)
    async def query(texts):
        return [[3.0, 4.0]]
    class Catalog:
        async def get_revision(self):
            return 2
        async def get_song_by_id(self, game, song_id):
            return songs[song_id]
    results = await cache.search_song_by_embedding(Catalog(), 'sdvx', 'new query', path=path, embedder=query, threshold=90)
    assert [(result.song_id, result.match_score) for result in results] == [(1, 100.0), (2, 96.0)]
    assert path.read_bytes() == original


@pytest.mark.asyncio
async def test_query_vectors_share_inference_survive_restart_and_isolate_providers(monkeypatch, tmp_path):
    from src.plugins.chiffon_bot.shared.search import embedding_cache as cache
    path = tmp_path / 'vectors.jsonl'
    provider = {'model': 'first', 'endpoint': 'http://first/embed'}
    monkeypatch.setattr(cache, 'embedding_model', lambda: provider['model'])
    monkeypatch.setattr(cache, 'embedding_endpoint', lambda: provider['endpoint'])
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []
    async def infer(texts):
        calls.append(texts)
        entered.set()
        await release.wait()
        return [[1.0, 0.0]]
    first = asyncio.create_task(cache._query_vector(path, 'new input', infer))
    second = asyncio.create_task(cache._query_vector(path, 'new input', infer))
    try:
        await entered.wait()
        first.cancel()  # One cancelled matcher must not cancel shared inference.
        await asyncio.gather(first, return_exceptions=True)
        release.set()
        assert await second == (1.0, 0.0)
        assert len(calls) == 1
        cache._QUERY_CACHE.clear()
        assert await cache._query_vector(path, 'new input', infer) == (1.0, 0.0)
        assert len(calls) == 1  # Loaded the persisted vector, without inference.
        provider['model'] = 'second'
        await cache._query_vector(path, 'new input', infer)
        provider['endpoint'] = 'http://second/embed'
        await cache._query_vector(path, 'new input', infer)
        assert len(calls) == 3
        attempts = 0
        async def unreliable(texts):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RuntimeError('offline')
            return [[0.0, 1.0]]
        with pytest.raises(RuntimeError, match='offline'):
            await cache._query_vector(path, 'retry input', unreliable)
        assert await cache._query_vector(path, 'retry input', unreliable) == (0.0, 1.0)
        assert attempts == 2
    finally:
        release.set()
        await cache._stop_query_tasks()


@pytest.mark.asyncio
async def test_incremental_song_vectors_reuse_text_and_preserve_file_on_failure(monkeypatch, tmp_path):
    from src.plugins.chiffon_bot.shared.search import embedding_cache as cache
    path = tmp_path / 'vectors.jsonl'
    provider = {'model': 'first', 'endpoint': 'http://first/embed'}
    monkeypatch.setattr(cache, 'embedding_model', lambda: provider['model'])
    monkeypatch.setattr(cache, 'embedding_endpoint', lambda: provider['endpoint'])
    songs = {1: SongData(id=1, title='First'), 2: SongData(id=2, title='Second')}
    calls = []
    async def infer(texts):
        calls.append(texts)
        return [[1.0, 0.0] for _ in texts]
    await cache.rebuild_song_embeddings_from_songs('game', songs, path=path, embedder=infer, revision=1)
    await cache.rebuild_song_embeddings_from_songs('game', songs, path=path, embedder=infer, revision=2)
    assert len(calls) == 1
    rows, matrix = cache._song_index(path, 'game')
    assert {row['revision'] for row in rows} == {2}
    await cache.rebuild_song_embeddings_from_songs('game', songs, path=path, embedder=infer, revision=2)
    assert cache._song_index(path, 'game')[1] is matrix
    await cache.rebuild_song_embeddings_from_songs('game', songs, alias_records=[(2, 'new alias')], path=path, embedder=infer, revision=3)
    assert calls[-1] == ['Second | new alias']
    binary = cache._game_path(path, 'game')
    before = binary.read_bytes()
    async def fail(texts):
        raise RuntimeError('offline')
    songs[1] = SongData(id=1, title='Changed')
    with pytest.raises(RuntimeError, match='offline'):
        await cache.rebuild_song_embeddings_from_songs('game', songs, path=path, embedder=fail, revision=4)
    assert binary.read_bytes() == before
    provider['model'] = 'second'
    await cache.rebuild_song_embeddings_from_songs('game', songs, path=path, embedder=infer, revision=4)
    assert calls[-1] == ['Changed', 'Second']
    provider['endpoint'] = 'http://second/embed'
    await cache.rebuild_song_embeddings_from_songs('game', songs, path=path, embedder=infer, revision=4)
    assert calls[-1] == ['Changed', 'Second']
    # A second game's concurrent publication must preserve both games.
    original_binary = binary.read_bytes()
    await cache.rebuild_song_embeddings_from_songs('other', songs, path=path, embedder=infer, revision=5)
    assert binary.read_bytes() == original_binary
    await asyncio.gather(*(cache.rebuild_song_embeddings_from_songs(game, songs, path=path, embedder=infer, revision=5)
                           for game in ('game', 'other')))
    assert cache.embedding_status(path)['songs'] == {'game': 2, 'other': 2}


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
async def test_tei_embed_provider_parses_direct_vector_response() -> None:
    from src.plugins.chiffon_bot.shared.search.embedding_provider import embed_texts

    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        assert payload == {
            "inputs": ["alpha", "beta"],
            "truncate": True,
        }
        return httpx.Response(200, json=[[1, 0], [0, 1]])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        vectors = await embed_texts(
            ["alpha", "beta"],
            endpoint="http://tei.test/embed",
            model="bge-m3",
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

    query_calls = []
    async def query_embedder(texts: list[str]) -> list[list[float]]:
        assert texts == ["semantic blue"]
        query_calls.append(texts)
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
    def no_disk_read(*args, **kwargs):
        raise AssertionError('Warm embedding search must not read JSONL again')
    monkeypatch.setattr(Path, 'read_text', no_disk_read)
    repeated = await embedding_cache.search_song_by_embedding(_Catalog(), 'quality', 'ｓｅｍａｎｔｉｃ blue', embedder=query_embedder)
    assert repeated[0].song_id == 1005 and len(query_calls) == 1


@pytest.mark.asyncio
async def test_embedding_cache_rejects_close_top_matches(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from src.plugins.chiffon_bot.shared.search import embedding_cache

    class _Catalog:
        songs = {
            1005: SongData(id=1005, title="Blue Noise", artist="Sakuzyo"),
            1006: SongData(id=1006, title="Red Noise", artist="Other"),
        }

        async def get_song_by_id(self, game_code: str, song_id: int) -> Any:
            return self.songs.get(song_id)

    path = tmp_path / "embeddings.jsonl"
    rows = [
        {"game": "quality", "song_id": 1005, "title": "Blue Noise", "vector": [1.0, 0.0]},
        {"game": "quality", "song_id": 1006, "title": "Red Noise", "vector": [0.999, 0.045]},
    ]
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )

    async def query_embedder(texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0]]

    monkeypatch.setattr(embedding_cache, "embedding_enabled", lambda: True)
    monkeypatch.setattr(embedding_cache, "embedding_path", lambda: path)

    results = await embedding_cache.search_song_by_embedding(
        _Catalog(),
        "quality",
        "semantic blue",
        embedder=query_embedder,
        threshold=55.0,
        min_margin=4.0,
    )

    assert results == []


@pytest.mark.asyncio
async def test_embedding_cache_margin_mode_returns_top_match_only(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from src.plugins.chiffon_bot.shared.search import embedding_cache

    class _Catalog:
        songs = {
            1005: SongData(id=1005, title="Blue Noise", artist="Sakuzyo"),
            1006: SongData(id=1006, title="Red Noise", artist="Other"),
        }

        async def get_song_by_id(self, game_code: str, song_id: int) -> Any:
            return self.songs.get(song_id)

    path = tmp_path / "embeddings.jsonl"
    rows = [
        {"game": "quality", "song_id": 1005, "title": "Blue Noise", "vector": [1.0, 0.0]},
        {"game": "quality", "song_id": 1006, "title": "Red Noise", "vector": [0.8, 0.6]},
    ]
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )

    async def query_embedder(texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0]]

    monkeypatch.setattr(embedding_cache, "embedding_enabled", lambda: True)
    monkeypatch.setattr(embedding_cache, "embedding_path", lambda: path)

    results = await embedding_cache.search_song_by_embedding(
        _Catalog(),
        "quality",
        "semantic blue",
        embedder=query_embedder,
        threshold=55.0,
        min_margin=4.0,
    )

    assert [result.song_id for result in results] == [1005]


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
    monkeypatch.setattr(embedding_cache, "embedding_rebuild_batch_size", lambda: 2)
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


@pytest.mark.asyncio
async def test_embedding_rebuild_reads_light_metadata_with_identical_text(monkeypatch, tmp_path):
    from src.plugins.chiffon_bot.shared.search import embedding_cache as cache
    class Catalog:
        async def load_all_songs(self, game):
            raise AssertionError('embedding must not load full songs')
        async def load_search_songs(self, game):
            return {7: SongData(id=7, title='Song', artist='Artist')}
        async def load_alias_records(self, game):
            return [(7, 'Ａlias'), (7, 'second')]
    calls = []
    async def infer(texts):
        calls.extend(texts)
        return [[1.0, 0.0] for _ in texts]
    await cache.rebuild_song_embeddings(Catalog(), 'sdvx', path=tmp_path / 'vectors.jsonl', embedder=infer)
    assert calls == [cache.build_embedding_text('Song', 'Artist', ['Ａlias', 'second'])]
