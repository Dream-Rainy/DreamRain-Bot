from __future__ import annotations

import json
from pathlib import Path

import pytest


QUALITY_CASES = Path("tests/fixtures/song_search_quality_cases.jsonl")


def _load_quality_cases() -> list[dict]:
    rows = []
    for line in QUALITY_CASES.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


@pytest.fixture(autouse=True)
def quality_adapter(app):
    from typing import Mapping

    from src.plugins.chiffon_bot.shared.game.registry import register_game_adapter
    from src.plugins.chiffon_bot.shared.search.song_query import invalidate_alias_cache
    from src.plugins.chiffon_bot.shared.song_data import SongData

    class _QualityAdapter:
        game_code = "quality"

        def __init__(self) -> None:
            self.songs = {
                1001: SongData(id=1001, title="Summer is over", artist="test"),
                1002: SongData(id=1002, title="ERIS -Legend of Gaidelia-", artist="test"),
            }
            self.aliases: dict[int, list[str]] = {
                song_id: [song.title]
                for song_id, song in self.songs.items()
            }

        def get_song_store(self) -> Mapping[int, SongData]:
            return self.songs

        def get_song_index(self) -> Mapping[int, str]:
            return {
                song_id: song.title
                for song_id, song in self.songs.items()
            }

        def get_song_title(self, song_data: SongData) -> str:
            return song_data.title

        async def get_song_by_id(self, song_id: int) -> SongData | None:
            return self.songs.get(song_id)

        async def load_all_songs(self) -> Mapping[int, SongData]:
            return self.songs

        async def query_alias_exact(self, alias_lower: str) -> list[tuple[int, str]]:
            matches: list[tuple[int, str]] = []
            for song_id, aliases in self.aliases.items():
                for alias in aliases:
                    if alias.lower() == alias_lower:
                        matches.append((song_id, alias))
            return matches

        async def load_alias_records(self) -> list[tuple[int, str]]:
            return [
                (song_id, alias)
                for song_id, aliases in self.aliases.items()
                for alias in aliases
            ]

        async def get_song_aliases_for_song_id(self, song_id: int) -> list[str]:
            return self.aliases.get(song_id, [])

        async def get_song_with_difficulty(
            self,
            song_id: int,
            song_type: str = "standard",
            level_index: int = 3,
        ) -> dict | None:
            return None

    register_game_adapter("quality", _QualityAdapter())
    invalidate_alias_cache("quality")
    yield
    invalidate_alias_cache("quality")


@pytest.mark.asyncio
@pytest.mark.parametrize("case", _load_quality_cases())
async def test_song_search_quality_cases(case: dict):
    from src.plugins.chiffon_bot.shared.search.song_query import search_song

    results = await search_song(case["query"], game_code=case["game"])
    result_ids = [result.song_id for result in results]

    if case.get("expected_empty") is True:
        assert result_ids == []
        return

    expected_top_id = case.get("expected_top_id")
    if expected_top_id is not None:
        assert result_ids
        assert result_ids[0] == expected_top_id

    for song_id in case.get("expected_include_ids") or []:
        assert song_id in result_ids

    for song_id in case.get("should_not_top_ids") or []:
        if result_ids:
            assert result_ids[0] != song_id


@pytest.mark.asyncio
async def test_song_search_audit_writes_editable_history(monkeypatch, tmp_path: Path):
    from src.plugins.chiffon_bot.shared.search.song_query import search_song

    audit_path = tmp_path / "song-search-history.jsonl"
    monkeypatch.setenv("SONG_SEARCH_AUDIT_LOG", "1")
    monkeypatch.setenv("SONG_SEARCH_AUDIT_PATH", str(audit_path))

    results = await search_song("eris", game_code="quality")

    assert results
    rows = [
        json.loads(line)
        for line in audit_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(rows) == 1
    row = rows[0]
    assert row["query"] == "eris"
    assert row["game"] == "quality"
    assert row["expected_top_id"] is None
    assert row["failure_reason"] is None
    assert row["results"][0]["song_id"] == 1002
