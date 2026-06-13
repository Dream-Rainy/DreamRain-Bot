from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        text = line.strip()
        if not text:
            continue
        try:
            row = json.loads(text)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"{path}:{line_no}: invalid JSONL row: {exc}") from exc
        row["_source"] = str(path)
        row["_line"] = line_no
        rows.append(row)
    return rows


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
    parser.add_argument("--failed-only", action="store_true")
    parser.add_argument("--empty-only", action="store_true")
    parser.add_argument("--annotated-only", action="store_true")
    parser.add_argument("--suspicious", action="store_true")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args()

    rows = [
        row
        for row in _iter_rows(args.paths)
        if _matches_filters(row, args)
    ]
    if args.limit > 0:
        rows = rows[:args.limit]

    if args.format == "json":
        for row in rows:
            print(json.dumps(row, ensure_ascii=False, sort_keys=True))
        return

    for row in rows:
        print(_summarize(row))


if __name__ == "__main__":
    main()
