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


@pytest.fixture
def quality_search():
    from arcade_helper.search import SongSearchService
    from arcade_helper.search.song_query import invalidate_alias_cache
    from arcade_helper.core.song import SongData

    class _QualityRepository:
        def __init__(self) -> None:
            self.songs_by_game = {
                "quality": {
                    1001: SongData(id=1001, title="Summer is over", artist="test"),
                    1002: SongData(id=1002, title="ERIS -Legend of Gaidelia-", artist="test"),
                }
            }
            self.aliases_by_game: dict[str, dict[int, list[str]]] = {}
            self.aliases_by_game["quality"] = {
                song_id: [song.title]
                for song_id, song in self.songs_by_game["quality"].items()
            }

        async def get_song_by_id(self, game_code: str, song_id: int) -> SongData | None:
            return self.songs_by_game[game_code].get(song_id)

        async def load_all_songs(self, game_code: str) -> dict[int, SongData]:
            return self.songs_by_game[game_code]

        async def load_song_index(self, game_code: str) -> dict[int, str]:
            return {
                song_id: song.title
                for song_id, song in self.songs_by_game[game_code].items()
            }

        async def query_alias_exact(self, game_code: str, alias_lower: str) -> list[tuple[int, str]]:
            matches: list[tuple[int, str]] = []
            for song_id, aliases in self.aliases_by_game[game_code].items():
                for alias in aliases:
                    if alias.lower() == alias_lower:
                        matches.append((song_id, alias))
            return matches

        async def load_alias_records(self, game_code: str) -> list[tuple[int, str]]:
            return [
                (song_id, alias)
                for song_id, aliases in self.aliases_by_game[game_code].items()
                for alias in aliases
            ]

        async def get_song_aliases_for_song_id(self, game_code: str, song_id: int) -> list[str]:
            return self.aliases_by_game[game_code].get(song_id, [])

        async def get_song_with_difficulty(
            self,
            game_code: str,
            song_id: int,
            song_type: str = "standard",
            level_index: int = 3,
        ) -> dict | None:
            return None

    repository = _QualityRepository()
    service = SongSearchService(repository)
    invalidate_alias_cache("quality")
    yield service
    invalidate_alias_cache("quality")


@pytest.mark.asyncio
@pytest.mark.parametrize("case", _load_quality_cases())
async def test_song_search_quality_cases(quality_search, case: dict):
    results = await quality_search.search_song(case["query"], game_code=case["game"])
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
async def test_song_search_audit_writes_editable_history(quality_search, monkeypatch, tmp_path: Path):
    from src.plugins.chiffon_bot.shared.search.catalog_search import search_song_with_audit
    from src.plugins.chiffon_bot.integrations.lxns.client import lxns_client

    class _Catalog:
        async def search_song(self, game_code: str, query: str | int):
            return await quality_search.search_song(query, game_code=game_code)

    audit_path = tmp_path / "song-search-history.jsonl"
    monkeypatch.setenv("SONG_SEARCH_AUDIT_LOG", "1")
    monkeypatch.setenv("SONG_SEARCH_AUDIT_PATH", str(audit_path))
    monkeypatch.setattr(lxns_client.data, "catalog", _Catalog())

    results = await search_song_with_audit("eris", game_code="quality")

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
