"""Bot-owned song search helpers.

Text search itself lives in ``arcade_helper``. This module adds bot-only
audit logging around the data-layer catalog search entrypoint.
"""

from __future__ import annotations

from time import monotonic
from uuid import uuid4

from arcade_helper.search import SongQueryResult

from ...integrations.lxns.client import lxns_client
from .search_audit import record_search_history


def _normalize_game_code(game_code: str) -> str:
    return str(game_code).strip().lower()


def _build_trace_id(query: str | int) -> str:
    q = str(query).replace("\n", " ").replace("\r", " ")
    return f"{q[:16]}:{uuid4().hex[:8]}"


def _query_norm(query: str | int) -> str:
    if not isinstance(query, str):
        return ""
    return query.strip().lower()


async def search_song_with_audit(
    query: str | int,
    *,
    game_code: str = "maimai",
) -> list[SongQueryResult]:
    gc = _normalize_game_code(game_code)
    trace_id = _build_trace_id(query)
    started_at = monotonic()
    results = await lxns_client.data.catalog.search_song(gc, query)
    record_search_history(
        query=query,
        game_code=gc,
        trace_id=trace_id,
        results=results,
        duration_ms=(monotonic() - started_at) * 1000.0,
        query_norm=_query_norm(query),
        prefix_retry_used=False,
        retry_query=None,
    )
    return results


__all__ = ["search_song_with_audit"]
