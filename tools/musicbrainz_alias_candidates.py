from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys
import time
from typing import Any, Callable
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import unicodedata


_ROOT = Path(__file__).resolve().parents[1]
_AUDIT_PATH = _ROOT / "src" / "plugins" / "chiffon_bot" / "shared" / "search" / "search_audit.py"
_AUDIT_SPEC = importlib.util.spec_from_file_location("song_search_audit", _AUDIT_PATH)
if _AUDIT_SPEC is None or _AUDIT_SPEC.loader is None:
    raise SystemExit(f"cannot load {_AUDIT_PATH}")
_AUDIT = importlib.util.module_from_spec(_AUDIT_SPEC)
_AUDIT_SPEC.loader.exec_module(_AUDIT)
alias_candidate_from_row = _AUDIT.alias_candidate_from_row


DEFAULT_USER_AGENT = "DreamRain-Bot/0.1 (https://github.com/DreamRain-Bot)"
DEFAULT_BASE_URL = "https://musicbrainz.org/ws/2/recording"


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
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _norm(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).lower()
    return "".join(ch for ch in normalized if ch.isalnum())


def _phrase(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _query(title: str, artist: str) -> str:
    parts = [f"recording:{_phrase(title)}"]
    if artist:
        parts.append(f"artist:{_phrase(artist)}")
    return " AND ".join(parts)


def _artist_names(recording: dict[str, Any]) -> list[str]:
    names: list[str] = []
    phrase = recording.get("artist-credit-phrase")
    if phrase:
        names.append(str(phrase))
    for credit in recording.get("artist-credit") or []:
        if not isinstance(credit, dict):
            continue
        artist = credit.get("artist")
        if isinstance(artist, dict) and artist.get("name"):
            names.append(str(artist["name"]))
        elif credit.get("name"):
            names.append(str(credit["name"]))
    return names


def _artist_matches(local_artist: str, recording: dict[str, Any]) -> bool:
    if not local_artist:
        return True
    local = _norm(local_artist)
    return any(local and local in _norm(name) for name in _artist_names(recording))


def _candidate_aliases(recording: dict[str, Any]) -> list[str]:
    aliases = [str(recording.get("title") or "").strip()]
    for alias in recording.get("aliases") or []:
        if isinstance(alias, dict):
            aliases.append(str(alias.get("name") or alias.get("alias") or "").strip())
    return [alias for alias in aliases if alias]


def _song_from_row(row: dict[str, Any]) -> dict[str, Any] | None:
    candidate = alias_candidate_from_row(row)
    evidence = (candidate or {}).get("evidence")
    if not isinstance(evidence, dict):
        evidence = {}
    song_id = row.get("song_id") or (candidate or {}).get("song_id")
    title = row.get("title") or (candidate or {}).get("title")
    artist = str(row.get("artist") or evidence.get("local_artist") or "").strip()
    artist_source = "row" if row.get("artist") else "candidate_evidence" if artist else ""
    if song_id is None or not title:
        results = row.get("results") or []
        if results:
            top = results[0]
            song_id = song_id or top.get("song_id")
            title = title or top.get("title")
            if not artist:
                artist = str(top.get("artist") or "").strip()
                artist_source = "top_result" if artist else ""
    if song_id is None or not title:
        return None
    return {
        "game": row.get("game") or (candidate or {}).get("game"),
        "song_id": int(song_id),
        "title": str(title),
        "artist": artist,
        "artist_source": artist_source,
    }


def iter_songs(paths: list[Path]) -> list[dict[str, Any]]:
    songs: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for path in paths:
        for row in _load_jsonl(path):
            song = _song_from_row(row)
            if song is None:
                continue
            key = (str(song.get("game") or ""), int(song["song_id"]))
            if key in seen:
                continue
            seen.add(key)
            songs.append(song)
    return songs


def fetch_musicbrainz(
    *,
    title: str,
    artist: str = "",
    base_url: str = DEFAULT_BASE_URL,
    user_agent: str = DEFAULT_USER_AGENT,
    limit: int = 5,
) -> dict[str, Any]:
    params = {
        "query": _query(title, artist),
        "fmt": "json",
        "limit": str(max(1, min(limit, 100))),
    }
    request = Request(
        base_url + "?" + urlencode(params),
        headers={
            "Accept": "application/json",
            "User-Agent": user_agent,
        },
    )
    with urlopen(request, timeout=20) as response:  # noqa: S310 - explicit user-triggered metadata lookup tool.
        return json.loads(response.read().decode("utf-8"))


def build_candidates(
    song: dict[str, Any],
    payload: dict[str, Any],
    *,
    min_score: int = 85,
) -> list[dict[str, Any]]:
    local_title = str(song["title"])
    local_artist = str(song.get("artist") or "")
    if not local_artist:
        return []

    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for recording in payload.get("recordings") or []:
        score = int(recording.get("score") or 0)
        if score < min_score or not _artist_matches(local_artist, recording):
            continue
        for alias in _candidate_aliases(recording):
            if _norm(alias) == _norm(local_title):
                continue
            key = _norm(alias)
            if not key or key in seen:
                continue
            seen.add(key)
            candidates.append({
                "schema_version": 1,
                "game": song.get("game"),
                "alias": alias,
                "song_id": int(song["song_id"]),
                "title": local_title,
                "confidence": round(score / 100.0, 3),
                "source": "musicbrainz",
                "status": "pending",
                "evidence": {
                    "local_title": local_title,
                    "local_artist": local_artist,
                    "local_artist_source": song.get("artist_source") or "",
                    "musicbrainz_recording_id": recording.get("id"),
                    "musicbrainz_title": recording.get("title"),
                    "musicbrainz_score": score,
                    "musicbrainz_artists": _artist_names(recording),
                },
            })
    return candidates


def generate_candidates(
    songs: list[dict[str, Any]],
    *,
    fetcher: Callable[..., dict[str, Any]] = fetch_musicbrainz,
    delay_seconds: float = 1.2,
    **kwargs: Any,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for index, song in enumerate(songs):
        if not song.get("artist"):
            continue
        if index:
            time.sleep(max(delay_seconds, 0.0))
        payload = fetcher(title=song["title"], artist=song.get("artist") or "", **kwargs)
        output.extend(build_candidates(song, payload))
    return output


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate pending song alias candidates from MusicBrainz search results.",
    )
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--user-agent", default=os.getenv("MUSICBRAINZ_USER_AGENT", DEFAULT_USER_AGENT))
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--sleep", type=float, default=1.2)
    parser.add_argument("--max-songs", type=int, default=0)
    args = parser.parse_args()

    songs = iter_songs(args.paths)
    if args.max_songs > 0:
        songs = songs[:args.max_songs]

    candidates = generate_candidates(
        songs,
        base_url=args.base_url,
        user_agent=args.user_agent,
        limit=args.limit,
        delay_seconds=args.sleep,
    )
    text = "".join(json.dumps(candidate, ensure_ascii=False, sort_keys=True) + "\n" for candidate in candidates)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
        return
    sys.stdout.write(text)


if __name__ == "__main__":
    main()
