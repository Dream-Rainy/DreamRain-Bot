"""Song-search embedding cache and fallback search."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Any, Awaitable, Callable

from nonebot import get_plugin_config
from arcade_helper.search import MatchType, SongQueryResult

from ...config import Config
from .embedding_provider import embed_texts, embedding_model


DEFAULT_EMBEDDING_PATH = Path("data") / "chiffon_bot" / "song_search_embeddings.jsonl"
DEFAULT_EMBEDDING_THRESHOLD = 80.0
_EMBEDDING_REBUILD_BATCH_SIZE = 128

Embedder = Callable[[list[str]], Awaitable[list[list[float]]]]


def embedding_enabled() -> bool:
    return bool(get_plugin_config(Config).song_search_embedding_enabled)


def embedding_path() -> Path:
    configured = get_plugin_config(Config).song_search_embedding_path.strip()
    return Path(configured) if configured else DEFAULT_EMBEDDING_PATH


def embedding_threshold() -> float:
    return float(get_plugin_config(Config).song_search_embedding_threshold)


def build_embedding_text(title: str, artist: str = "", aliases: list[str] | None = None) -> str:
    seen: set[str] = set()
    parts: list[str] = []
    for item in [title, artist, *(aliases or [])]:
        text = str(item or "").strip()
        key = text.lower()
        if not text or key in seen:
            continue
        seen.add(key)
        parts.append(text)
    return " | ".join(parts)


def _vector_from_row(row: dict[str, Any]) -> list[float] | None:
    raw = row.get("vector") or row.get("embedding")
    if not isinstance(raw, list) or not raw:
        return None
    try:
        vector = [float(item) for item in raw]
    except (TypeError, ValueError):
        return None
    return vector if any(value != 0.0 for value in vector) else None


def _load_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            row = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fp:
            for row in rows:
                fp.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
                fp.write("\n")
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def embedding_status(path: Path | None = None) -> dict[str, Any]:
    target = path or embedding_path()
    rows = _load_rows(target)
    counts: dict[str, int] = defaultdict(int)
    models: set[str] = set()
    for row in rows:
        if row.get("song_id") is None:
            continue
        counts[str(row.get("game") or "")] += 1
        if row.get("model"):
            models.add(str(row["model"]))
    return {
        "path": str(target),
        "exists": target.exists(),
        "songs": dict(sorted(counts.items())),
        "models": sorted(models),
    }


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (left_norm * right_norm)


async def rebuild_song_embeddings(
    catalog: Any,
    game_code: str,
    *,
    path: Path | None = None,
    embedder: Embedder = embed_texts,
) -> dict[str, Any]:
    game = str(game_code).strip().lower()
    songs = await catalog.load_all_songs(game)
    alias_records = await catalog.load_alias_records(game)
    return await rebuild_song_embeddings_from_songs(
        game,
        songs,
        alias_records=alias_records,
        path=path,
        embedder=embedder,
    )


async def rebuild_song_embeddings_from_songs(
    game_code: str,
    songs: dict[int, Any],
    *,
    alias_records: list[tuple[int, str]] | None = None,
    path: Path | None = None,
    embedder: Embedder = embed_texts,
) -> dict[str, Any]:
    game = str(game_code).strip().lower()
    target = path or embedding_path()

    aliases_by_song_id: dict[int, list[str]] = defaultdict(list)
    for song_id, alias in alias_records or []:
        aliases_by_song_id[int(song_id)].append(str(alias))

    metadata: list[dict[str, Any]] = []
    texts: list[str] = []
    for song_id, song in sorted(songs.items()):
        title = str(getattr(song, "title", "") or "")
        artist = str(getattr(song, "artist", "") or "")
        text = build_embedding_text(title, artist, aliases_by_song_id.get(int(song_id), []))
        if not text:
            continue
        metadata.append({
            "game": game,
            "song_id": int(song_id),
            "title": title,
            "artist": artist,
            "text": text,
        })
        texts.append(text)

    vectors: list[list[float]] = []
    for start in range(0, len(texts), _EMBEDDING_REBUILD_BATCH_SIZE):
        vectors.extend(await embedder(texts[start:start + _EMBEDDING_REBUILD_BATCH_SIZE]))
    if len(vectors) != len(metadata):
        raise ValueError(f"embedding count mismatch: expected {len(metadata)}, got {len(vectors)}")

    now = datetime.now().astimezone().isoformat(timespec="seconds")
    existing = [
        row for row in _load_rows(target)
        if not (str(row.get("game") or "").lower() == game and row.get("song_id") is not None)
    ]
    model = embedding_model()
    rebuilt = [
        {
            **item,
            "model": model,
            "updated_at": now,
            "vector": vector,
        }
        for item, vector in zip(metadata, vectors, strict=True)
    ]
    _write_rows(target, existing + rebuilt)
    return {"game": game, "songs": len(rebuilt), "path": str(target), "model": model}


async def search_song_by_embedding(
    catalog: Any,
    game_code: str,
    query: str,
    *,
    path: Path | None = None,
    embedder: Embedder = embed_texts,
) -> list[SongQueryResult]:
    if not embedding_enabled():
        return []
    query_text = str(query or "").strip()
    if not query_text:
        return []

    game = str(game_code).strip().lower()
    target = path or embedding_path()
    song_rows = [
        row for row in _load_rows(target)
        if str(row.get("game") or "").lower() == game and row.get("song_id") is not None
    ]
    if not song_rows:
        return []

    query_vectors = await embedder([query_text])
    if not query_vectors:
        return []
    query_vector = query_vectors[0]

    scored: list[tuple[float, dict[str, Any]]] = []
    threshold = embedding_threshold()
    for row in song_rows:
        vector = _vector_from_row(row)
        if vector is None:
            continue
        score = _cosine_similarity(query_vector, vector) * 100.0
        if score >= threshold:
            scored.append((score, row))

    scored.sort(key=lambda item: item[0], reverse=True)
    results: list[SongQueryResult] = []
    seen: set[int] = set()
    for score, row in scored[:10]:
        song_id = int(row["song_id"])
        if song_id in seen:
            continue
        song_data = await catalog.get_song_by_id(game, song_id)
        if not song_data:
            continue
        seen.add(song_id)
        results.append(SongQueryResult(
            song_id=song_id,
            title=str(getattr(song_data, "title", "") or row.get("title") or ""),
            match_type=MatchType.EMBEDDING,
            match_score=round(score, 3),
            matched_text=query_text,
            song_data=song_data,
        ))
    return results
