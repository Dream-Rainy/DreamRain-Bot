"""Song-search reranker helpers."""

from __future__ import annotations

from typing import Any

from nonebot import get_plugin_config
from arcade_helper.search import SongQueryResult

from ...config import Config
from .reranker_provider import rerank_texts


def reranker_enabled() -> bool:
    return bool(get_plugin_config(Config).song_search_reranker_enabled)


def reranker_threshold() -> float:
    return float(get_plugin_config(Config).song_search_reranker_threshold)


def reranker_min_margin() -> float:
    return float(get_plugin_config(Config).song_search_reranker_min_margin)


def _song_text(result: SongQueryResult, aliases: list[str]) -> str:
    song_data = result.song_data
    artist = str(getattr(song_data, "artist", "") or "").strip()
    parts = [result.title, artist, *aliases]
    seen: set[str] = set()
    texts: list[str] = []
    for part in parts:
        text = str(part or "").strip()
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            texts.append(text)
    return " | ".join(texts)


def song_work_key(result: SongQueryResult, game_code: str | None = None):
    """Only persisted work links may merge entries across games."""
    song = result.song_data
    return getattr(song, "work_id", None) or (getattr(song, "game_code", None) or game_code, result.song_id)


async def rerank_song_results(
    catalog: Any,
    game_code: str | None,
    query: str,
    results: list[SongQueryResult],
    *,
    limit: int = 10,
    score_cache: dict | None = None,
) -> list[SongQueryResult] | None:
    if not reranker_enabled():
        return None
    if not results:
        return []

    works = {}
    for result in sorted(results, key=lambda r: r.match_score, reverse=True):
        works.setdefault(song_work_key(result, game_code), result)
    candidates = list(works.values())[:limit]
    documents: list[str] = []
    for result in candidates:
        aliases = getattr(result.song_data, "aliases", None)
        if aliases is None or (hasattr(result.song_data, "model_fields_set") and "aliases" not in result.song_data.model_fields_set):
            try:
                aliases = await catalog.get_song_aliases_for_song_id(getattr(result.song_data, "game_code", None) or game_code, result.song_id)
            except Exception:
                aliases = []
        documents.append(_song_text(result, aliases))

    key = (str(query), tuple(documents))
    if score_cache is not None and key in score_cache:
        scores = score_cache[key]
    else:
        scores = await rerank_texts(str(query), documents)
        if score_cache is not None:
            score_cache[key] = scores
    if not scores:
        return []

    scored = sorted(zip(scores, candidates, strict=True), key=lambda item: item[0], reverse=True)
    top_score = scored[0][0]
    if top_score < reranker_threshold():
        return []
    if len(scored) > 1 and top_score - scored[1][0] < reranker_min_margin():
        return []
    selected = song_work_key(scored[0][1], game_code)
    return [result for result in results if song_work_key(result, game_code) == selected]
