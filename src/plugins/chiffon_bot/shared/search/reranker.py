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


async def rerank_song_results(
    catalog: Any,
    game_code: str,
    query: str,
    results: list[SongQueryResult],
    *,
    limit: int = 10,
) -> list[SongQueryResult]:
    if not reranker_enabled() or len(results) < 2:
        return []

    candidates = results[:limit]
    documents: list[str] = []
    for result in candidates:
        try:
            aliases = await catalog.get_song_aliases_for_song_id(game_code, result.song_id)
        except Exception:
            aliases = []
        documents.append(_song_text(result, aliases))

    scores = await rerank_texts(str(query), documents)
    if not scores:
        return []

    scored = sorted(zip(scores, candidates, strict=True), key=lambda item: item[0], reverse=True)
    top_score = scored[0][0]
    if top_score < reranker_threshold():
        return []
    if len(scored) > 1 and top_score - scored[1][0] < reranker_min_margin():
        return []
    return [scored[0][1]]
