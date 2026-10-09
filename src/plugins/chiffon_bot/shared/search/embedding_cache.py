"""Song-search embedding cache and fallback search."""

from __future__ import annotations

import asyncio
from collections import defaultdict, OrderedDict
from datetime import datetime
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Any, Awaitable, Callable
from urllib.parse import quote

import numpy as np

from nonebot import get_plugin_config, logger
from arcade_helper.search import MatchType, SongQueryResult
from arcade_helper.core.song_identity import normalize_width

from ...config import Config
from .embedding_provider import embed_texts, embedding_model, embedding_endpoint


DEFAULT_EMBEDDING_PATH = Path("data") / "chiffon_bot" / "song_search_embeddings.jsonl"
DEFAULT_EMBEDDING_THRESHOLD = 80.0
_EMBEDDING_REBUILD_BATCH_SIZE = 32
_QUERY_CACHE_LIMIT = 512
_ROWS_CACHE = {}
_INDEX_CACHE = {}
_QUERY_CACHE = OrderedDict()
_QUERY_TASKS = {}
_FILE_LOCKS = {}
_REBUILD_LOCKS = {}

Embedder = Callable[[list[str]], Awaitable[list[list[float]]]]


def embedding_enabled() -> bool:
    return bool(get_plugin_config(Config).song_search_embedding_enabled)


def embedding_path() -> Path:
    configured = get_plugin_config(Config).song_search_embedding_path.strip()
    return Path(configured) if configured else DEFAULT_EMBEDDING_PATH


def embedding_threshold() -> float:
    return float(get_plugin_config(Config).song_search_embedding_threshold)


def embedding_rebuild_batch_size() -> int:
    configured = int(get_plugin_config(Config).song_search_embedding_rebuild_batch_size)
    return configured if configured > 0 else _EMBEDDING_REBUILD_BATCH_SIZE


def build_embedding_text(title: str, artist: str = "", aliases: list[str] | None = None) -> str:
    seen: set[str] = set()
    parts: list[str] = []
    for item in [title, artist, *sorted(aliases or [])]:
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
    return vector if all(math.isfinite(v) for v in vector) and any(value != 0.0 for value in vector) else None


def _file_token(path: Path):
    try:
        stat = path.stat()
        return stat.st_mtime_ns, stat.st_size
    except FileNotFoundError:
        return None


def _load_rows(path: Path) -> list[dict[str, Any]]:
    key = str(path.resolve())
    token = _file_token(path)
    cached = _ROWS_CACHE.get(key)
    if cached is not None and cached[0] == token:
        return cached[1]
    if token is None:
        return []
    rows: list[dict[str, Any]] = []
    for line in _iter_lines(path):
        text = line.strip()
        if not text:
            continue
        try:
            row = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    _ROWS_CACHE[key] = (token, rows)
    return rows


def _iter_lines(path):
    with path.open(encoding="utf-8") as stream:
        yield from stream


def _write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fp:
            for row in rows:
                fp.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
                fp.write("\n")
        os.replace(temp_name, path)
        _ROWS_CACHE.pop(str(path.resolve()), None)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def embedding_status(path: Path | None = None) -> dict[str, Any]:
    target = path or embedding_path()
    counts: dict[str, int] = defaultdict(int)
    models: set[str] = set()
    # Read metadata only; status must not allocate the vector matrices.
    rows = []
    for binary in target.parent.glob(f"{target.stem}.*.npz"):
        with np.load(binary, allow_pickle=False) as data:
            rows.extend(json.loads(str(data["metadata"])))
    binary_games = {row.get("game") for row in rows}
    if target.exists():
        for line in _iter_lines(target):
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict) and row.get("game") not in binary_games:
                rows.append({key: value for key, value in row.items() if key not in {"vector", "embedding"}})
    for row in rows:
        if row.get("song_id") is None:
            continue
        counts[str(row.get("game") or "")] += 1
        if row.get("model"):
            models.add(str(row["model"]))
    return {
        "path": str(target),
        "exists": target.exists() or bool(counts),
        "songs": dict(sorted(counts.items())),
        "models": sorted(models),
    }


def _unit_vector(vector):
    norm = math.sqrt(sum(value * value for value in vector))
    return tuple(value / norm for value in vector) if norm and math.isfinite(norm) else ()


def _game_path(path: Path, game: str) -> Path:
    return path.with_name(f"{path.stem}.{quote(game, safe='')}.npz")


def _pack_vectors(rows, vectors):
    matrix = np.asarray(vectors, dtype=np.float32)
    if not rows:
        matrix = np.empty((0, 0), dtype=np.float32)
    if matrix.ndim != 2 or len(matrix) != len(rows) or not np.isfinite(matrix).all():
        raise ValueError("Invalid song embedding matrix")
    norms = np.linalg.norm(matrix, axis=1)
    if np.any(norms == 0) or not np.isfinite(norms).all():
        raise ValueError("Invalid song embedding norm")
    matrix /= norms[:, None]
    matrix.setflags(write=False)
    return rows, matrix


def _write_index(path, rows, matrix):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            np.savez(stream, metadata=np.array(json.dumps(rows, ensure_ascii=False)), vectors=matrix)
        os.replace(temporary, path)
        _INDEX_CACHE[str(path.resolve())] = (_file_token(path), (rows, matrix))
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _song_index(path: Path, game: str):
    binary = _game_path(path, game)
    key = str(binary.resolve())
    token = _file_token(binary) or _file_token(path)
    cached = _INDEX_CACHE.get(key)
    if cached is not None and cached[0] == token:
        return cached[1]
    if binary.exists():
        with np.load(binary, allow_pickle=False) as data:
            rows = json.loads(str(data["metadata"]))
            matrix = data["vectors"]
        if matrix.dtype != np.float32 or matrix.ndim != 2 or len(matrix) != len(rows) or not np.isfinite(matrix).all():
            raise ValueError("Invalid cached song embedding matrix")
        matrix.setflags(write=False)
        index = rows, matrix
    else:
        rows, vectors = [], []
        # Stream legacy JSONL once per game, without retaining Python float lists.
        for line in _iter_lines(path) if path.exists() else ():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict) or str(row.get("game", "")).lower() != game or row.get("song_id") is None:
                continue
            vector = _vector_from_row(row)
            if vector and (not vectors or len(vector) == len(vectors[0])):
                rows.append({key: value for key, value in row.items() if key not in {"vector", "embedding"}})
                vectors.append(np.asarray(vector, dtype=np.float32))
        index = _pack_vectors(rows, vectors)
    _INDEX_CACHE[key] = (token, index)
    return index


async def _query_vector(target: Path, text: str, embedder: Embedder):
    model, endpoint = embedding_model(), embedding_endpoint()
    path = target.with_name(f'{target.stem}.queries{target.suffix}')
    key = (str(path.resolve()), endpoint, model, text)
    if key in _QUERY_CACHE:
        _QUERY_CACHE.move_to_end(key)
        return _QUERY_CACHE[key]

    async def compute():
        rows = await asyncio.to_thread(_load_rows, path)
        row = next((r for r in reversed(rows) if (r.get('endpoint'), r.get('model'), r.get('query')) == key[1:]), None)
        vector = _vector_from_row(row) if row else None
        if vector is None:
            vectors = await (embed_texts([text], endpoint=endpoint, model=model) if embedder is embed_texts else embedder([text]))
            vector = _vector_from_row({'vector': vectors[0]}) if len(vectors) == 1 else None
            if vector is None:
                raise ValueError('Invalid query embedding')
            lock = _FILE_LOCKS.setdefault(str(path.resolve()), asyncio.Lock())
            async with lock:
                rows = list(await asyncio.to_thread(_load_rows, path))
                rows.append({'query': text, 'endpoint': endpoint, 'model': model, 'vector': vector})
                try:
                    await asyncio.to_thread(_write_rows, path, rows[-_QUERY_CACHE_LIMIT:])
                except OSError as exc:
                    logger.warning(f'查询向量缓存写入失败，保留内存缓存: {exc}')
        _QUERY_CACHE[key] = _unit_vector(vector)
        while len(_QUERY_CACHE) > _QUERY_CACHE_LIMIT:
            _QUERY_CACHE.popitem(last=False)
        return _QUERY_CACHE[key]

    task = _QUERY_TASKS.get(key)
    if task is None:
        task = _QUERY_TASKS[key] = asyncio.create_task(compute())
        def done(completed):
            _QUERY_TASKS.pop(key, None)
            if not completed.cancelled():
                completed.exception()  # Observe failures even when every waiting matcher was cancelled.
        task.add_done_callback(done)
    return await asyncio.shield(task)


async def _stop_query_tasks():
    tasks = list(_QUERY_TASKS.values())
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


async def rebuild_song_embeddings(
    catalog: Any,
    game_code: str,
    *,
    path: Path | None = None,
    embedder: Embedder = embed_texts,
) -> dict[str, Any]:
    game = str(game_code).strip().lower()
    get_revision = getattr(catalog, "get_revision", None)
    revision = await get_revision() if get_revision else None
    inputs = getattr(catalog, "load_embedding_inputs", None)
    if inputs is not None:
        songs, alias_records = await inputs(game)
    else:
        load = getattr(catalog, "load_search_songs", catalog.load_all_songs)
        songs = await load(game)
        alias_records = await catalog.load_alias_records(game)
    if get_revision and await get_revision() != revision:
        raise ValueError("曲库已变化，请重新构建 embedding")
    return await rebuild_song_embeddings_from_songs(
        game,
        songs,
        alias_records=alias_records,
        path=path,
        embedder=embedder,
        revision=revision,
    )


async def rebuild_song_embeddings_from_songs(
    game_code: str,
    songs: dict[int, Any],
    *,
    alias_records: list[tuple[int, str]] | None = None,
    path: Path | None = None,
    embedder: Embedder = embed_texts,
    revision: int | None = None,
) -> dict[str, Any]:
    game = str(game_code).strip().lower()
    target = path or embedding_path()
    lock = _REBUILD_LOCKS.setdefault((str(target.resolve()), game), asyncio.Lock())
    async with lock:
        return await _rebuild_song_embeddings(game, songs, alias_records, target, embedder, revision)


async def _rebuild_song_embeddings(game, songs, alias_records, target, embedder, revision):
    model, endpoint = embedding_model(), embedding_endpoint()
    old_rows, old_matrix = await asyncio.to_thread(_song_index, target, game)
    previous = {
        row['text']: vector for row, vector in zip(old_rows, old_matrix, strict=True)
        if row.get('game') == game and row.get('model') == model and row.get('endpoint') == endpoint
        and row.get('text')
    }

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

    pending = list(dict.fromkeys(text for text in texts if text not in previous))
    batch_size = embedding_rebuild_batch_size()
    for start in range(0, len(pending), batch_size):
        batch = pending[start:start + batch_size]
        vectors = await (embed_texts(batch, endpoint=endpoint, model=model) if embedder is embed_texts else embedder(batch))
        if len(vectors) != len(batch):
            raise ValueError(f"embedding count mismatch: expected {len(batch)}, got {len(vectors)}")
        for text, vector in zip(batch, vectors, strict=True):
            checked = _vector_from_row({'vector': vector})
            if checked is None:
                raise ValueError('Invalid song embedding')
            previous[text] = checked

    now = datetime.now().astimezone().isoformat(timespec="seconds")
    rebuilt = [
        {
            **item,
            "model": model,
            "endpoint": endpoint,
            "updated_at": now,
            "revision": revision,
        }
        for item in metadata
    ]
    unchanged = not pending and len(old_rows) == len(rebuilt) and all(
        old.get('song_id') == row['song_id'] and old.get('text') == row['text']
        for old, row in zip(old_rows, rebuilt, strict=True)
    )
    matrix = old_matrix if unchanged else (await asyncio.to_thread(
        _pack_vectors, rebuilt, [previous[item['text']] for item in metadata]
    ))[1]
    await asyncio.to_thread(_write_index, _game_path(target, game), rebuilt, matrix)
    return {"game": game, "songs": len(rebuilt), "path": str(target), "model": model}


async def search_song_by_embedding(
    catalog: Any,
    game_code: str,
    query: str,
    *,
    path: Path | None = None,
    embedder: Embedder = embed_texts,
    threshold: float | None = None,
    min_margin: float | None = None,
) -> list[SongQueryResult]:
    if not embedding_enabled():
        return []
    query_text = normalize_width(str(query or "")).strip()
    if not query_text:
        return []

    game = str(game_code).strip().lower()
    target = path or embedding_path()
    get_revision = getattr(catalog, "get_revision", None)
    revision = await get_revision() if get_revision else None
    rows, matrix = await asyncio.to_thread(_song_index, target, game)
    model, endpoint = embedding_model(), embedding_endpoint()
    indices = [index for index, row in enumerate(rows)
                 if row.get('revision') == revision
                 and (row.get('model') == model or (revision is None and not row.get('model')))
                 and (row.get('endpoint') == endpoint or (revision is None and not row.get('endpoint')))]
    if not indices:
        return []

    query_vector = await _query_vector(target, query_text, embedder)

    scored: list[tuple[float, dict[str, Any]]] = []
    effective_threshold = embedding_threshold() if threshold is None else float(threshold)
    if matrix.shape[1] != len(query_vector):
        return []
    # BLAS and sorting run off the message loop; keep the cached matrix shared.
    def rank():
        scores = matrix @ np.asarray(query_vector, dtype=np.float32) * 100.0
        order = sorted(indices, key=lambda index: float(scores[index]), reverse=True)[:10]
        return [(float(scores[index]), rows[index]) for index in order]
    scored = await asyncio.to_thread(rank)
    if not scored or scored[0][0] < effective_threshold:
        return []
    if min_margin is not None and len(scored) > 1 and scored[0][0] - scored[1][0] < float(min_margin):
        return []

    results: list[SongQueryResult] = []
    seen: set[int] = set()
    limit = 1 if min_margin is not None else 10
    for score, row in scored[:limit]:
        if score < effective_threshold:
            break
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
    if get_revision and await get_revision() != revision:
        return []
    return results
