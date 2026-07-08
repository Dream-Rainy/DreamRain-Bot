"""Minimal HTTP service for BGE-M3 embeddings via FlagEmbedding.

Run:
    uv run uvicorn tools.bge_m3_service:app --host 0.0.0.0 --port 11436
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel


DEFAULT_MODEL_ID = "BAAI/bge-m3"
DEFAULT_RERANKER_MODEL_ID = "BAAI/bge-reranker-v2-m3"
DEFAULT_BATCH_SIZE = 32


class EmbedRequest(BaseModel):
    texts: list[str] | str | None = None
    inputs: list[str] | str | None = None
    return_sparse: bool = False
    return_colbert: bool = False


class EmbedResponse(BaseModel):
    embeddings: list[list[float]]
    sparse: list[dict[str, float]] | None = None
    colbert: list[list[list[float]]] | None = None


class RerankRequest(BaseModel):
    query: str
    texts: list[str] | None = None
    documents: list[str] | None = None


class RerankItem(BaseModel):
    index: int
    score: float


app = FastAPI(title="BGE-M3 Embedding Service")


def _texts(value: list[str] | str) -> list[str]:
    if isinstance(value, str):
        value = [value]
    return [text.strip() for text in value if text.strip()]


def _to_builtin(value: Any) -> Any:
    if hasattr(value, "tolist"):
        return value.tolist()
    if isinstance(value, dict):
        return {str(key): float(val) for key, val in value.items()}
    if isinstance(value, list):
        return [_to_builtin(item) for item in value]
    return value


@lru_cache(maxsize=1)
def _model():
    from FlagEmbedding import BGEM3FlagModel

    model_id = os.getenv("BGE_M3_MODEL", DEFAULT_MODEL_ID)
    device = os.getenv("BGE_M3_DEVICE", "").strip() or None
    use_fp16 = os.getenv("BGE_M3_USE_FP16", "1").strip().lower() not in {"0", "false", "no", "off"}
    kwargs: dict[str, Any] = {"use_fp16": use_fp16}
    if device:
        kwargs["device"] = device
    return BGEM3FlagModel(model_id, **kwargs)


@lru_cache(maxsize=1)
def _reranker():
    from FlagEmbedding import FlagReranker

    model_id = os.getenv("BGE_RERANKER_MODEL", DEFAULT_RERANKER_MODEL_ID)
    device = os.getenv("BGE_RERANKER_DEVICE", "").strip() or None
    use_fp16 = os.getenv("BGE_RERANKER_USE_FP16", "1").strip().lower() not in {"0", "false", "no", "off"}
    kwargs: dict[str, Any] = {"use_fp16": use_fp16}
    if device:
        kwargs["device"] = device
    try:
        return FlagReranker(model_id, **kwargs)
    except TypeError:
        kwargs.pop("device", None)
        return FlagReranker(model_id, **kwargs)


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "model": os.getenv("BGE_M3_MODEL", DEFAULT_MODEL_ID),
        "reranker_model": os.getenv("BGE_RERANKER_MODEL", DEFAULT_RERANKER_MODEL_ID),
        "loaded": _model.cache_info().currsize > 0,
        "reranker_loaded": _reranker.cache_info().currsize > 0,
    }


@app.post("/embed", response_model=EmbedResponse)
def embed(request: EmbedRequest) -> dict[str, Any]:
    texts = _texts(request.texts if request.texts is not None else request.inputs or [])
    if not texts:
        return {"embeddings": []}

    batch_size = int(os.getenv("BGE_M3_BATCH_SIZE", str(DEFAULT_BATCH_SIZE)))
    output = _model().encode(
        texts,
        batch_size=batch_size,
        return_dense=True,
        return_sparse=request.return_sparse,
        return_colbert_vecs=request.return_colbert,
    )
    response: dict[str, Any] = {"embeddings": _to_builtin(output["dense_vecs"])}
    if request.return_sparse:
        response["sparse"] = _to_builtin(output.get("lexical_weights", []))
    if request.return_colbert:
        response["colbert"] = _to_builtin(output.get("colbert_vecs", []))
    return response


@app.post("/embed-hybrid", response_model=EmbedResponse)
def embed_hybrid(request: EmbedRequest) -> dict[str, Any]:
    request.return_sparse = True
    request.return_colbert = True
    return embed(request)


@app.post("/rerank", response_model=list[RerankItem])
def rerank(request: RerankRequest) -> list[dict[str, float | int]]:
    query = request.query.strip()
    documents = _texts(request.texts if request.texts is not None else request.documents or [])
    if not query or not documents:
        return []

    batch_size = int(os.getenv("BGE_RERANKER_BATCH_SIZE", str(DEFAULT_BATCH_SIZE)))
    pairs = [[query, document] for document in documents]
    scores = _to_builtin(_reranker().compute_score(pairs, batch_size=batch_size))
    if isinstance(scores, (int, float)):
        scores = [float(scores)]
    items = [
        {"index": index, "score": float(score)}
        for index, score in enumerate(scores)
    ]
    return sorted(items, key=lambda item: item["score"], reverse=True)
