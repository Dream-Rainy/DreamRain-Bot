from __future__ import annotations

import json

import httpx
import pytest


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
