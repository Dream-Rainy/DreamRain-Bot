from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


def _load_tool():
    path = Path("tools/musicbrainz_alias_candidates.py").resolve()
    spec = importlib.util.spec_from_file_location("musicbrainz_alias_candidates", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_musicbrainz_candidates_keep_artist_matched_title_variants() -> None:
    tool = _load_tool()
    song = {
        "game": "quality",
        "song_id": 1005,
        "title": "Blue Noise",
        "artist": "Sakuzyo",
    }
    payload = {
        "recordings": [
            {
                "id": "mb-good",
                "score": 98,
                "title": "青いノイズ",
                "artist-credit": [{"artist": {"name": "Sakuzyo"}}],
            },
            {
                "id": "mb-same",
                "score": 99,
                "title": "Blue Noise",
                "artist-credit": [{"artist": {"name": "Sakuzyo"}}],
            },
            {
                "id": "mb-wrong-artist",
                "score": 99,
                "title": "Blue Noise Alternate",
                "artist-credit": [{"artist": {"name": "Other"}}],
            },
        ],
    }

    candidates = tool.build_candidates(song, payload)

    assert [candidate["alias"] for candidate in candidates] == ["青いノイズ"]
    assert candidates[0]["source"] == "musicbrainz"
    assert candidates[0]["status"] == "pending"
    assert candidates[0]["evidence"]["musicbrainz_recording_id"] == "mb-good"


def test_musicbrainz_generate_candidates_uses_fetcher_without_network() -> None:
    tool = _load_tool()
    calls: list[tuple[str, str]] = []

    def fake_fetcher(**kwargs):
        calls.append((kwargs["title"], kwargs["artist"]))
        return {
            "recordings": [
                {
                    "id": "mbid",
                    "score": 90,
                    "title": "Alias Title",
                    "artist-credit": [{"artist": {"name": kwargs["artist"]}}],
                }
            ]
        }

    candidates = tool.generate_candidates(
        [{"game": "quality", "song_id": 1, "title": "Local Title", "artist": "Artist"}],
        fetcher=fake_fetcher,
        delay_seconds=0,
    )

    assert calls == [("Local Title", "Artist")]
    assert candidates[0]["alias"] == "Alias Title"


def test_musicbrainz_generate_candidates_skips_title_only_rows() -> None:
    tool = _load_tool()
    calls: list[tuple[str, str]] = []

    def fake_fetcher(**kwargs):
        calls.append((kwargs["title"], kwargs["artist"]))
        return {"recordings": []}

    tool.generate_candidates(
        [
            {"game": "quality", "song_id": 1, "title": "No Artist", "artist": ""},
            {"game": "quality", "song_id": 2, "title": "Has Artist", "artist": "Artist"},
        ],
        fetcher=fake_fetcher,
        delay_seconds=0,
    )

    assert calls == [("Has Artist", "Artist")]


def test_musicbrainz_iter_songs_reads_artist_from_audit_result(tmp_path: Path) -> None:
    tool = _load_tool()
    source = tmp_path / "history.jsonl"
    source.write_text(
        json.dumps({
            "game": "quality",
            "query": "blue noise",
            "results": [
                {
                    "song_id": 1005,
                    "title": "Blue Noise",
                    "artist": "Sakuzyo",
                    "rank": 1,
                }
            ],
        }, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    songs = tool.iter_songs([source])

    assert songs == [{
        "game": "quality",
        "song_id": 1005,
        "title": "Blue Noise",
        "artist": "Sakuzyo",
        "artist_source": "top_result",
    }]


def test_musicbrainz_import_appends_pending_candidates(tmp_path: Path) -> None:
    from src.plugins.chiffon_bot.shared.search.search_audit import (
        import_alias_candidates,
        list_alias_candidates,
    )

    source = tmp_path / "musicbrainz.jsonl"
    target = tmp_path / "history.jsonl"
    source.write_text(
        json.dumps({
            "schema_version": 1,
            "game": "quality",
            "alias": "青いノイズ",
            "song_id": 1005,
            "title": "Blue Noise",
            "confidence": 0.98,
            "source": "musicbrainz",
            "status": "pending",
            "evidence": {"musicbrainz_recording_id": "mb-good"},
        }, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    assert import_alias_candidates(source, path=target) == 1
    assert import_alias_candidates(source, path=target) == 0

    candidates = list_alias_candidates(path=target)
    assert len(candidates) == 1
    assert candidates[0]["alias"] == "青いノイズ"
    assert candidates[0]["source"] == "musicbrainz"


def test_musicbrainz_import_rejects_missing_file(tmp_path: Path) -> None:
    from src.plugins.chiffon_bot.shared.search.search_audit import import_alias_candidates

    with pytest.raises(ValueError, match="JSONL file not found"):
        import_alias_candidates(tmp_path / "missing.jsonl")
