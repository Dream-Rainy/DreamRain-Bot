"""Search history auditing for song lookup quality work.

The audit path is intentionally best-effort: failures here must never affect
normal song search.
"""

from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import tempfile
import threading
from typing import Any, Iterable

from nonebot import logger


_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}
_DEFAULT_AUDIT_PATH = Path("data") / "chiffon_bot" / "song_search_history.jsonl"
_VALID_CANDIDATE_STATUSES = {"pending", "accepted", "rejected"}
_NON_ALIAS_MATCH_TYPES = {"exact_id", "exact_title", "exact_alias"}
_AUDIT_LOCK = threading.RLock()
_ACCEPTED_ALIAS_CACHE: dict[
    tuple[str, str],
    tuple[tuple[int, int] | None, list[tuple[int, str]]],
] = {}


def _audit_mode() -> str:
    return os.getenv("SONG_SEARCH_AUDIT_LOG", "suspicious").strip().lower()


def _audit_enabled_for(is_suspicious: bool) -> bool:
    mode = _audit_mode()
    if mode in _FALSE_VALUES:
        return False
    if mode in _TRUE_VALUES or mode == "all":
        return True
    return is_suspicious


def _audit_path() -> Path:
    configured = os.getenv("SONG_SEARCH_AUDIT_PATH", "").strip()
    return Path(configured) if configured else _DEFAULT_AUDIT_PATH


def _path_key(path: Path) -> str:
    return str(path.resolve())


def _file_token(path: Path) -> tuple[int, int] | None:
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None
    return (stat.st_mtime_ns, stat.st_size)


def _invalidate_accepted_alias_cache(path: Path | None = None) -> None:
    if path is None:
        _ACCEPTED_ALIAS_CACHE.clear()
        return

    target = _path_key(path)
    for key in list(_ACCEPTED_ALIAS_CACHE):
        if key[0] == target:
            del _ACCEPTED_ALIAS_CACHE[key]


def _result_to_dict(result: Any, rank: int) -> dict[str, Any]:
    song_data = getattr(result, "song_data", None)
    artist = str(getattr(song_data, "artist", "") or "").strip()
    return {
        "rank": rank,
        "song_id": int(result.song_id),
        "title": str(result.title),
        "artist": artist,
        "match_type": result.match_type.value,
        "score": round(float(result.match_score), 3),
        "matched_text": str(result.matched_text),
    }


def _is_suspicious(query: str | int, result_rows: list[dict[str, Any]]) -> bool:
    query_text = str(query or "")
    if not result_rows:
        return True
    top = result_rows[0]
    if float(top.get("score") or 0.0) < 85.0:
        return True
    return query_text.isascii() and 1 <= len(query_text) <= 4


def _should_audit(is_suspicious: bool, result_rows: list[dict[str, Any]]) -> bool:
    if _audit_mode() in _FALSE_VALUES:
        return False
    if result_rows and result_rows[0].get("match_type") == "embedding":
        return True
    return _audit_enabled_for(is_suspicious)


def _alias_candidate(
    query: str | int,
    result_rows: list[dict[str, Any]],
    *,
    game_code: str,
    path: Path | None = None,
) -> dict[str, Any] | None:
    if not result_rows:
        return None
    top = result_rows[0]
    if str(top.get("match_type") or "") in _NON_ALIAS_MATCH_TYPES:
        return None
    song_id = top.get("song_id")
    if song_id is None:
        return None
    alias = str(query).strip()
    if not alias or alias.isdigit():
        return None
    alias_key = alias.lower()
    if any(
        accepted_song_id == int(song_id) and accepted_alias.lower() == alias_key
        for accepted_song_id, accepted_alias in accepted_alias_records(game_code, path)
    ):
        return None
    return {
        "alias": alias,
        "song_id": int(song_id),
        "title": str(top.get("title") or ""),
        "source": "search_audit",
        "confidence": round(float(top.get("score") or 0.0) / 100.0, 3),
        "status": "pending",
    }


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []

    rows: list[dict[str, Any]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        text = line.strip()
        if not text:
            continue
        try:
            row = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_no}: invalid JSONL row: {exc}") from exc
        if isinstance(row, dict):
            row["_source"] = str(path)
            row["_line"] = line_no
            rows.append(row)
    return rows


def _dump_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    # ponytail: rewrite the small audit file; move to append-only events if review volume grows.
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fp:
            for row in rows:
                clean = {
                    key: value
                    for key, value in row.items()
                    if not key.startswith("_")
                }
                fp.write(json.dumps(clean, ensure_ascii=False, sort_keys=True))
                fp.write("\n")
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
    _invalidate_accepted_alias_cache(path)


def alias_candidate_from_row(row: dict[str, Any]) -> dict[str, Any] | None:
    candidate = row.get("alias_candidate")
    if not isinstance(candidate, dict) or candidate.get("song_id") is None:
        return None

    return {
        "schema_version": 1,
        "game": row.get("game"),
        "alias": candidate.get("alias") or row.get("query"),
        "song_id": int(candidate["song_id"]),
        "title": candidate.get("title") or "",
        "confidence": float(candidate.get("confidence") or 0.0),
        "source": candidate.get("source") or "search_audit",
        "status": candidate.get("status") or "pending",
        "line": row.get("_line"),
        "evidence": {
            **(candidate.get("evidence") if isinstance(candidate.get("evidence"), dict) else {}),
            "query": row.get("query"),
            "trace_id": row.get("trace_id"),
            "top_match_type": row.get("top_match_type"),
            "top_score": row.get("top_score"),
            "history_source": f"{row.get('_source')}:{row.get('_line')}",
        },
    }


def _candidate_key(candidate: dict[str, Any]) -> tuple[str, int, str, str]:
    return (
        str(candidate.get("game") or "").strip().lower(),
        int(candidate["song_id"]),
        str(candidate.get("alias") or "").strip().lower(),
        str(candidate.get("source") or "").strip().lower(),
    )


def _history_record_for_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    alias = str(candidate.get("alias") or "").strip()
    if not alias:
        raise ValueError("candidate alias is required")
    if candidate.get("song_id") is None:
        raise ValueError("candidate song_id is required")

    source = str(candidate.get("source") or "manual_import")
    evidence = candidate.get("evidence") if isinstance(candidate.get("evidence"), dict) else {}
    return {
        "schema_version": 1,
        "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
        "game": str(candidate.get("game") or "").strip(),
        "query": alias,
        "query_norm": alias.lower(),
        "trace_id": str(evidence.get("trace_id") or f"{source}:{candidate.get('song_id')}"),
        "duration_ms": 0.0,
        "prefix_retry_used": False,
        "retry_query": None,
        "top_song_id": int(candidate["song_id"]),
        "top_match_type": source,
        "top_score": round(float(candidate.get("confidence") or 0.0) * 100.0, 3),
        "is_suspicious": True,
        "alias_candidate": {
            "alias": alias,
            "song_id": int(candidate["song_id"]),
            "title": str(candidate.get("title") or ""),
            "source": source,
            "confidence": round(float(candidate.get("confidence") or 0.0), 3),
            "status": str(candidate.get("status") or "pending"),
            "evidence": evidence,
        },
        "results": [],
        "expected_top_id": None,
        "expected_include_ids": [],
        "should_not_top_ids": [],
        "expected_empty": None,
        "failure_reason": None,
        "notes": candidate.get("notes"),
    }


def append_alias_candidate(
    candidate: dict[str, Any],
    *,
    path: Path | None = None,
) -> bool:
    record = _history_record_for_candidate(candidate)
    audit_path = path or _audit_path()
    imported = alias_candidate_from_row(record)
    if imported is None:
        return False

    with _AUDIT_LOCK:
        existing = {
            _candidate_key(existing_candidate)
            for row in _load_jsonl(audit_path)
            if (existing_candidate := alias_candidate_from_row(row)) is not None
        }
        if _candidate_key(imported) in existing:
            return False

        audit_path.parent.mkdir(parents=True, exist_ok=True)
        with audit_path.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(record, ensure_ascii=False, sort_keys=True))
            fp.write("\n")
        _invalidate_accepted_alias_cache(audit_path)
    return True


def import_alias_candidates(
    source_path: Path,
    *,
    path: Path | None = None,
) -> int:
    if not source_path.exists():
        raise ValueError(f"JSONL file not found: {source_path}")

    count = 0
    for row in _load_jsonl(source_path):
        candidate = row if "alias" in row else alias_candidate_from_row(row)
        if candidate is None:
            continue
        candidate = dict(candidate)
        candidate["status"] = "pending"
        if append_alias_candidate(candidate, path=path):
            count += 1
    return count


def accepted_alias_records(game_code: str, path: Path | None = None) -> list[tuple[int, str]]:
    game = str(game_code).strip().lower()
    audit_path = path or _audit_path()
    cache_key = (_path_key(audit_path), game)
    token = _file_token(audit_path)

    with _AUDIT_LOCK:
        cached = _ACCEPTED_ALIAS_CACHE.get(cache_key)
        if cached is not None and cached[0] == token:
            return list(cached[1])

    records: list[tuple[int, str]] = []
    seen: set[tuple[int, str]] = set()
    with _AUDIT_LOCK:
        for row in _load_jsonl(audit_path):
            candidate = alias_candidate_from_row(row)
            if candidate is None or candidate["status"] != "accepted":
                continue
            if str(candidate.get("game") or "").strip().lower() != game:
                continue
            alias = str(candidate.get("alias") or "").strip()
            if not alias:
                continue
            item = (int(candidate["song_id"]), alias)
            key = (item[0], alias.lower())
            if key in seen:
                continue
            seen.add(key)
            records.append(item)
        _ACCEPTED_ALIAS_CACHE[cache_key] = (token, records)
    return records


def query_accepted_alias_exact(
    game_code: str,
    alias_lower: str,
    path: Path | None = None,
) -> list[tuple[int, str]]:
    key = str(alias_lower).lower()
    return [
        (song_id, alias)
        for song_id, alias in accepted_alias_records(game_code, path)
        if alias.lower() == key
    ]


def accepted_aliases_for_song_id(
    game_code: str,
    song_id: int,
    path: Path | None = None,
) -> list[str]:
    target = int(song_id)
    return [
        alias
        for candidate_song_id, alias in accepted_alias_records(game_code, path)
        if candidate_song_id == target
    ]


def load_search_history(path: Path | None = None) -> list[dict[str, Any]]:
    """Load editable search history rows with source line metadata."""

    return _load_jsonl(path or _audit_path())


def list_alias_candidates(
    *,
    status: str = "pending",
    limit: int = 20,
    path: Path | None = None,
) -> list[dict[str, Any]]:
    rows = load_search_history(path)
    candidates: list[dict[str, Any]] = []
    for row in reversed(rows):
        candidate = alias_candidate_from_row(row)
        if candidate is None:
            continue
        if status != "all" and candidate["status"] != status:
            continue
        candidates.append(candidate)
        if limit > 0 and len(candidates) >= limit:
            break
    return candidates


def get_search_history_row(line_no: int, path: Path | None = None) -> dict[str, Any] | None:
    for row in load_search_history(path):
        if row.get("_line") == line_no:
            return row
    return None


def update_alias_candidate_status(
    line_no: int,
    status: str,
    *,
    reviewer: str | None = None,
    path: Path | None = None,
) -> dict[str, Any]:
    if status not in _VALID_CANDIDATE_STATUSES:
        raise ValueError(f"invalid alias candidate status: {status}")

    audit_path = path or _audit_path()
    with _AUDIT_LOCK:
        rows = _load_jsonl(audit_path)
        for row in rows:
            if row.get("_line") != line_no:
                continue
            candidate = row.get("alias_candidate")
            if not isinstance(candidate, dict):
                raise ValueError(f"line {line_no} has no alias candidate")
            candidate["status"] = status
            candidate["reviewed_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
            if reviewer:
                candidate["reviewer"] = reviewer
            _dump_jsonl(audit_path, rows)
            updated = alias_candidate_from_row(row)
            if updated is None:
                raise ValueError(f"line {line_no} has no alias candidate")
            return updated

    raise ValueError(f"line {line_no} not found")


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

    try:
        result_rows = [
            _result_to_dict(result, rank)
            for rank, result in enumerate(results, start=1)
        ]
        suspicious = _is_suspicious(query, result_rows)
        if not _should_audit(suspicious, result_rows):
            return

        path = _audit_path()
        top = result_rows[0] if result_rows else None
        top_match_type = top.get("match_type") if top else None
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
            "top_song_id": top.get("song_id") if top else None,
            "top_match_type": top_match_type,
            "top_score": top.get("score") if top else None,
            "is_suspicious": suspicious,
            "alias_candidate": _alias_candidate(
                query,
                result_rows,
                game_code=game_code,
                path=path,
            ) if suspicious or top_match_type == "embedding" else None,
            "results": result_rows,
            "expected_top_id": None,
            "expected_include_ids": [],
            "should_not_top_ids": [],
            "expected_empty": None,
            "failure_reason": None,
            "notes": None,
        }

        path.parent.mkdir(parents=True, exist_ok=True)
        with _AUDIT_LOCK, path.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(record, ensure_ascii=False, sort_keys=True))
            fp.write("\n")
    except Exception as exc:
        logger.warning(f"[song_search_audit] write failed: {exc}")
