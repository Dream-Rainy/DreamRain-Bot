"""Local HTTP embedding provider helpers."""

from __future__ import annotations

from typing import Any

import httpx
from nonebot import get_plugin_config

from ...config import Config


DEFAULT_EMBEDDING_ENDPOINT = "http://127.0.0.1:11434/api/embed"
DEFAULT_EMBEDDING_MODEL = "embeddinggemma"


class EmbeddingProviderError(RuntimeError):
    """Raised when the local embedding endpoint returns unusable data."""


def embedding_endpoint() -> str:
    return get_plugin_config(Config).song_search_embedding_endpoint.strip() or DEFAULT_EMBEDDING_ENDPOINT


def embedding_model() -> str:
    return get_plugin_config(Config).song_search_embedding_model.strip() or DEFAULT_EMBEDDING_MODEL


def _coerce_vectors(value: Any) -> list[list[float]]:
    if not isinstance(value, list):
        raise EmbeddingProviderError("embedding response is not a list")
    if value and all(isinstance(item, (int, float)) for item in value):
        value = [value]
    vectors: list[list[float]] = []
    for raw_vector in value:
        if not isinstance(raw_vector, list) or not raw_vector:
            raise EmbeddingProviderError("embedding vector is empty or invalid")
        try:
            vectors.append([float(item) for item in raw_vector])
        except (TypeError, ValueError) as exc:
            raise EmbeddingProviderError("embedding vector contains non-numeric values") from exc
    return vectors


def _is_ollama_endpoint(endpoint: str) -> bool:
    return endpoint.rstrip("/").endswith("/api/embed")


async def _request_embeddings(
    texts: list[str],
    *,
    endpoint: str | None = None,
    model: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> tuple[list[str], Any]:
    clean_texts = [text.strip() for text in texts if text.strip()]
    if not clean_texts:
        return [], None

    target_endpoint = endpoint or embedding_endpoint()
    if _is_ollama_endpoint(target_endpoint):
        payload = {
            "model": model or embedding_model(),
            "input": clean_texts if len(clean_texts) > 1 else clean_texts[0],
        }
    else:
        payload = {
            "inputs": clean_texts if len(clean_texts) > 1 else clean_texts[0],
            "truncate": True,
        }
    close_client = client is None
    client = client or httpx.AsyncClient(timeout=60)
    try:
        response = await client.post(target_endpoint, json=payload)
        response.raise_for_status()
        data = response.json()
    finally:
        if close_client:
            await client.aclose()
    return clean_texts, data


async def embed_texts(
    texts: list[str],
    *,
    endpoint: str | None = None,
    model: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> list[list[float]]:
    clean_texts, data = await _request_embeddings(texts, endpoint=endpoint, model=model, client=client)
    if not clean_texts:
        return []
    vectors = _coerce_vectors(
        data if isinstance(data, list) else data.get("embeddings") or data.get("embedding")
    )
    if len(vectors) != len(clean_texts):
        raise EmbeddingProviderError(
            f"embedding count mismatch: expected {len(clean_texts)}, got {len(vectors)}"
        )
    return vectors
