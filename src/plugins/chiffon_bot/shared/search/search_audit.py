"""Search history auditing for song lookup quality work.

The audit path is intentionally best-effort: failures here must never affect
normal song search.
"""

from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
from typing import Any, Iterable

from nonebot import logger


_TRUE_VALUES = {"1", "true", "yes", "on"}
_DEFAULT_AUDIT_PATH = Path("data") / "chiffon_bot" / "song_search_history.jsonl"


def _audit_enabled() -> bool:
    return os.getenv("SONG_SEARCH_AUDIT_LOG", "").strip().lower() in _TRUE_VALUES


def _audit_path() -> Path:
    configured = os.getenv("SONG_SEARCH_AUDIT_PATH", "").strip()
    return Path(configured) if configured else _DEFAULT_AUDIT_PATH


def _result_to_dict(result: Any, rank: int) -> dict[str, Any]:
    return {
        "rank": rank,
        "song_id": int(result.song_id),
        "title": str(result.title),
        "match_type": result.match_type.value,
        "score": round(float(result.match_score), 3),
        "matched_text": str(result.matched_text),
    }


def record_search_history(
    *,
    query: str | int,
    game_code: str,
    trace_id: str,
    results: Iterable[Any],
    duration_ms: float,
    query_norm: str = "",
    prefix_retry_used: bool = False,
    retry_query: str | None = None,
) -> None:
    """Append one editable JSONL row for a completed user-facing search."""

    if not _audit_enabled():
        return

    try:
        result_rows = [
            _result_to_dict(result, rank)
            for rank, result in enumerate(results, start=1)
        ]
        record = {
            "schema_version": 1,
            "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
            "game": game_code,
            "query": str(query),
            "query_norm": query_norm,
            "trace_id": trace_id,
            "duration_ms": round(duration_ms, 3),
            "prefix_retry_used": prefix_retry_used,
            "retry_query": retry_query,
            "results": result_rows,
            "expected_top_id": None,
            "expected_include_ids": [],
            "should_not_top_ids": [],
            "expected_empty": None,
            "failure_reason": None,
            "notes": None,
        }

        path = _audit_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(record, ensure_ascii=False, sort_keys=True))
            fp.write("\n")
    except Exception as exc:
        logger.warning(f"[song_search_audit] write failed: {exc}")
