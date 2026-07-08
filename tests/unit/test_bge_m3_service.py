from __future__ import annotations

from fastapi.testclient import TestClient

from tools import bge_m3_service


def test_bge_m3_service_embed_accepts_inputs(monkeypatch) -> None:
    class _Model:
        def encode(self, texts, **kwargs):
            assert texts == ["alpha", "beta"]
            assert kwargs["return_dense"] is True
            return {"dense_vecs": [[1, 0], [0, 1]]}

    monkeypatch.setattr(bge_m3_service, "_model", lambda: _Model())

    client = TestClient(bge_m3_service.app)
    response = client.post("/embed", json={"inputs": ["alpha", "beta"]})

    assert response.status_code == 200
    assert response.json() == {"embeddings": [[1.0, 0.0], [0.0, 1.0]], "sparse": None, "colbert": None}


def test_bge_m3_service_embed_hybrid_returns_sparse_and_colbert(monkeypatch) -> None:
    class _Model:
        def encode(self, texts, **kwargs):
            assert texts == ["alpha"]
            assert kwargs["return_sparse"] is True
            assert kwargs["return_colbert_vecs"] is True
            return {
                "dense_vecs": [[1, 0]],
                "lexical_weights": [{"alpha": 0.7}],
                "colbert_vecs": [[[1, 0], [0, 1]]],
            }

    monkeypatch.setattr(bge_m3_service, "_model", lambda: _Model())

    client = TestClient(bge_m3_service.app)
    response = client.post("/embed-hybrid", json={"texts": ["alpha"]})

    assert response.status_code == 200
    assert response.json() == {
        "embeddings": [[1.0, 0.0]],
        "sparse": [{"alpha": 0.7}],
        "colbert": [[[1.0, 0.0], [0.0, 1.0]]],
    }


def test_bge_m3_service_rerank_returns_indexed_scores(monkeypatch) -> None:
    class _Reranker:
        def compute_score(self, pairs, **kwargs):
            assert pairs == [["query", "first"], ["query", "second"]]
            assert kwargs["batch_size"] == 32
            return [0.1, 0.9]

    monkeypatch.setattr(bge_m3_service, "_reranker", lambda: _Reranker())

    client = TestClient(bge_m3_service.app)
    response = client.post("/rerank", json={"query": "query", "texts": ["first", "second"]})

    assert response.status_code == 200
    assert response.json() == [
        {"index": 1, "score": 0.9},
        {"index": 0, "score": 0.1},
    ]
