from __future__ import annotations

import json

import httpx
import pytest


@pytest.mark.asyncio
async def test_reranker_reuses_loaded_aliases_with_legacy_repository_fallback(monkeypatch):
    from arcade_helper.core.song import SongData
    from arcade_helper.search import SongQueryResult, MatchType
    from src.plugins.chiffon_bot.shared.search import reranker
    monkeypatch.setattr(reranker, 'reranker_enabled', lambda: True)
    monkeypatch.setattr(reranker, 'reranker_threshold', lambda: 0)
    monkeypatch.setattr(reranker, 'reranker_min_margin', lambda: 0)
    songs = [SongData(id=1, title='First', aliases=['cached alias']), SongData(id=2, title='Second')]
    results = [SongQueryResult(song.id, song.title, MatchType.FUZZY_TITLE, 90, '', song) for song in songs]
    looked_up = []
    class Catalog:
        async def get_song_aliases_for_song_id(self, game, song_id):
            looked_up.append(song_id)
            return ['legacy alias']
    async def rank(query, documents):
        assert documents == ['First | cached alias', 'Second | legacy alias']
        return [0.9, 0.1]
    monkeypatch.setattr(reranker, 'rerank_texts', rank)
    assert await reranker.rerank_song_results(Catalog(), 'sdvx', 'input', results) == [results[0]]
    assert looked_up == [2]


@pytest.mark.asyncio
async def test_reranker_provider_parses_scores_response() -> None:
    from src.plugins.chiffon_bot.shared.search.reranker_provider import rerank_texts

    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        assert payload == {
            "model": "bge-reranker-v2-m3",
            "query": "semantic query",
            "texts": ["first", "second"],
            "documents": ["first", "second"],
        }
        return httpx.Response(200, json={"scores": [0.1, 0.9]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        scores = await rerank_texts(
            "semantic query",
            ["first", "second"],
            endpoint="http://reranker.test/rerank",
            model="bge-reranker-v2-m3",
            client=client,
        )

    assert scores == [0.1, 0.9]


@pytest.mark.asyncio
async def test_reranker_provider_parses_tei_indexed_response() -> None:
    from src.plugins.chiffon_bot.shared.search.reranker_provider import rerank_texts

    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        assert payload["texts"] == ["first", "second"]
        return httpx.Response(200, json=[
            {"index": 1, "score": 0.9},
            {"index": 0, "score": 0.1},
        ])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        scores = await rerank_texts(
            "semantic query",
            ["first", "second"],
            endpoint="http://tei.test/rerank",
            client=client,
        )

    assert scores == [0.1, 0.9]


@pytest.mark.asyncio
async def test_reranker_provider_rejects_score_count_mismatch() -> None:
    from src.plugins.chiffon_bot.shared.search.reranker_provider import (
        RerankerProviderError,
        rerank_texts,
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"scores": [0.1]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(RerankerProviderError, match="score count mismatch"):
            await rerank_texts(
                "semantic query",
                ["first", "second"],
                endpoint="http://reranker.test/rerank",
                client=client,
            )
