from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Iterable

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_AUDIT_PATH = _ROOT / "src" / "plugins" / "chiffon_bot" / "shared" / "search" / "search_audit.py"
_AUDIT_SPEC = importlib.util.spec_from_file_location("song_search_audit", _AUDIT_PATH)
if _AUDIT_SPEC is None or _AUDIT_SPEC.loader is None:
    raise SystemExit(f"cannot load {_AUDIT_PATH}")
_AUDIT = importlib.util.module_from_spec(_AUDIT_SPEC)
_AUDIT_SPEC.loader.exec_module(_AUDIT)
alias_candidate_from_row = _AUDIT.alias_candidate_from_row
load_search_history = _AUDIT.load_search_history


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        return load_search_history(path)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc


def _top_id(row: dict[str, Any]) -> int | None:
    results = row.get("results") or []
    if not results:
        return None
    song_id = results[0].get("song_id")
    return int(song_id) if song_id is not None else None


def _score(row: dict[str, Any]) -> float:
    results = row.get("results") or []
    if not results:
        return 0.0
    return float(results[0].get("score") or 0.0)


def _match_type(row: dict[str, Any]) -> str:
    top_match_type = row.get("top_match_type")
    if top_match_type:
        return str(top_match_type)
    results = row.get("results") or []
    if not results:
        return "empty"
    return str(results[0].get("match_type") or "unknown")


def _fails_expectation(row: dict[str, Any]) -> bool:
    results = row.get("results") or []
    result_ids = [
        int(result["song_id"])
        for result in results
        if result.get("song_id") is not None
    ]

    if row.get("expected_empty") is True and result_ids:
        return True
    if row.get("expected_empty") is False and not result_ids:
        return True

    expected_top_id = row.get("expected_top_id")
    if expected_top_id is not None and _top_id(row) != int(expected_top_id):
        return True

    for song_id in row.get("expected_include_ids") or []:
        if int(song_id) not in result_ids:
            return True

    for song_id in row.get("should_not_top_ids") or []:
        if _top_id(row) == int(song_id):
            return True

    return False


def _is_suspicious(row: dict[str, Any]) -> bool:
    query = str(row.get("query") or "")
    results = row.get("results") or []
    if not results:
        return True
    if _score(row) < 85.0:
        return True
    if query.isascii() and 1 <= len(query) <= 4:
        return True
    return False


def _matches_filters(row: dict[str, Any], args: argparse.Namespace) -> bool:
    if args.game and str(row.get("game")) != args.game:
        return False
    if args.query and args.query.lower() not in str(row.get("query") or "").lower():
        return False
    if args.reason and str(row.get("failure_reason") or "") != args.reason:
        return False
    if args.match_type and _match_type(row) != args.match_type:
        return False
    if args.empty_only and row.get("results"):
        return False
    if args.annotated_only and not _has_expectation(row):
        return False
    if args.failed_only and not _fails_expectation(row):
        return False
    if args.suspicious and not _is_suspicious(row):
        return False
    return True


def _has_expectation(row: dict[str, Any]) -> bool:
    return (
        row.get("expected_top_id") is not None
        or bool(row.get("expected_include_ids"))
        or bool(row.get("should_not_top_ids"))
        or row.get("expected_empty") is not None
    )


def _summarize(row: dict[str, Any]) -> str:
    top = _top_id(row)
    status = "FAIL" if _fails_expectation(row) else "ok"
    reason = row.get("failure_reason") or "-"
    source = f"{row.get('_source')}:{row.get('_line')}"
    return (
        f"{status:4} game={row.get('game')} query={row.get('query')!r} "
        f"top={top} score={_score(row):.1f} reason={reason} source={source}"
    )


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_match_type: dict[str, dict[str, Any]] = {}
    for row in rows:
        match_type = _match_type(row)
        bucket = by_match_type.setdefault(
            match_type,
            {"count": 0, "failed": 0, "empty": 0, "score_sum": 0.0},
        )
        bucket["count"] += 1
        bucket["failed"] += int(_fails_expectation(row))
        bucket["empty"] += int(not bool(row.get("results")))
        bucket["score_sum"] += _score(row)

    match_types: dict[str, dict[str, Any]] = {}
    for match_type, bucket in sorted(by_match_type.items()):
        count = int(bucket["count"])
        match_types[match_type] = {
            "count": count,
            "failed": int(bucket["failed"]),
            "empty": int(bucket["empty"]),
            "avg_score": round(float(bucket["score_sum"]) / count, 3) if count else 0.0,
        }

    return {
        "total": len(rows),
        "failed": sum(1 for row in rows if _fails_expectation(row)),
        "empty": sum(1 for row in rows if not row.get("results")),
        "match_types": match_types,
    }


def _print_summary(summary: dict[str, Any]) -> None:
    print(f"total={summary['total']} failed={summary['failed']} empty={summary['empty']}")
    for match_type, bucket in summary["match_types"].items():
        print(
            f"{match_type}: count={bucket['count']} failed={bucket['failed']} "
            f"empty={bucket['empty']} avg_score={bucket['avg_score']:.1f}"
        )


def _alias_candidate(row: dict[str, Any]) -> dict[str, Any] | None:
    candidate = alias_candidate_from_row(row)
    if candidate is not None:
        return candidate

    results = row.get("results") or []
    if not results:
        return None
    top = results[0]
    song_id = top.get("song_id")
    if song_id is None:
        return None
    return {
        "schema_version": 1,
        "game": row.get("game"),
        "alias": row.get("query"),
        "song_id": int(song_id),
        "title": top.get("title") or "",
        "confidence": round(float(top.get("score") or 0.0) / 100.0, 3),
        "source": "search_audit",
        "status": "pending",
        "evidence": {
            "query": row.get("query"),
            "trace_id": row.get("trace_id"),
            "top_match_type": top.get("match_type"),
            "top_score": top.get("score"),
            "history_source": f"{row.get('_source')}:{row.get('_line')}",
        },
    }


def _iter_rows(paths: Iterable[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in paths:
        rows.extend(_load_jsonl(path))
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Inspect editable song-search history/case JSONL files.",
    )
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--game")
    parser.add_argument("--query")
    parser.add_argument("--reason")
    parser.add_argument("--match-type")
    parser.add_argument("--failed-only", action="store_true")
    parser.add_argument("--empty-only", action="store_true")
    parser.add_argument("--annotated-only", action="store_true")
    parser.add_argument("--suspicious", action="store_true")
    parser.add_argument("--alias-candidates", action="store_true")
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args()

    rows = [
        row
        for row in _iter_rows(args.paths)
        if _matches_filters(row, args)
    ]
    limit = args.limit if args.limit is not None else (0 if args.summary else 50)
    if limit > 0:
        rows = rows[:limit]

    if args.alias_candidates:
        for row in rows:
            candidate = _alias_candidate(row)
            if candidate is not None:
                print(json.dumps(candidate, ensure_ascii=False, sort_keys=True))
        return

    if args.summary:
        summary = _summary(rows)
        if args.format == "json":
            print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
            return
        _print_summary(summary)
        return

    if args.format == "json":
        for row in rows:
            print(json.dumps(row, ensure_ascii=False, sort_keys=True))
        return

    for row in rows:
        print(_summarize(row))


if __name__ == "__main__":
    main()
