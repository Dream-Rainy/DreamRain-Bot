"""Local HTTP reranker provider helpers."""

from __future__ import annotations

from typing import Any

import httpx
from nonebot import get_plugin_config

from ...config import Config


DEFAULT_RERANKER_ENDPOINT = "http://127.0.0.1:11435/rerank"
DEFAULT_RERANKER_MODEL = "bge-reranker-v2-m3"


class RerankerProviderError(RuntimeError):
    """Raised when the local reranker endpoint returns unusable data."""


def reranker_endpoint() -> str:
    return get_plugin_config(Config).song_search_reranker_endpoint.strip() or DEFAULT_RERANKER_ENDPOINT


def reranker_model() -> str:
    return get_plugin_config(Config).song_search_reranker_model.strip() or DEFAULT_RERANKER_MODEL


def _coerce_scores(data: Any, expected_count: int) -> list[float]:
    if isinstance(data, list):
        scores_by_index: dict[int, float] = {}
        for item in data:
            if not isinstance(item, dict) or item.get("index") is None:
                raise RerankerProviderError("reranker list response requires index fields")
            try:
                scores_by_index[int(item["index"])] = float(item["score"])
            except (KeyError, TypeError, ValueError) as exc:
                raise RerankerProviderError("reranker indexed scores are invalid") from exc
        try:
            return [scores_by_index[index] for index in range(expected_count)]
        except KeyError as exc:
            raise RerankerProviderError("reranker indexed scores are incomplete") from exc

    raw_scores = data.get("scores") if isinstance(data, dict) else None
    if raw_scores is None and isinstance(data, dict):
        results = data.get("results")
        if isinstance(results, list):
            raw_scores = [item.get("score") for item in results if isinstance(item, dict)]
    if not isinstance(raw_scores, list):
        raise RerankerProviderError("reranker response does not contain scores")
    try:
        return [float(score) for score in raw_scores]
    except (TypeError, ValueError) as exc:
        raise RerankerProviderError("reranker scores contain non-numeric values") from exc


async def rerank_texts(
    query: str,
    documents: list[str],
    *,
    endpoint: str | None = None,
    model: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> list[float]:
    clean_query = str(query or "").strip()
    clean_documents = [document.strip() for document in documents if document.strip()]
    if not clean_query or not clean_documents:
        return []

    payload = {
        "model": model or reranker_model(),
        "query": clean_query,
        "texts": clean_documents,
        "documents": clean_documents,
    }
    close_client = client is None
    client = client or httpx.AsyncClient(timeout=60)
    try:
        response = await client.post(endpoint or reranker_endpoint(), json=payload)
        response.raise_for_status()
        scores = _coerce_scores(response.json(), len(clean_documents))
    finally:
        if close_client:
            await client.aclose()

    if len(scores) != len(clean_documents):
        raise RerankerProviderError(
            f"reranker score count mismatch: expected {len(clean_documents)}, got {len(scores)}"
        )
    return scores
