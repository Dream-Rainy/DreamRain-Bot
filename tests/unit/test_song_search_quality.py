from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

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
                    1003: SongData(id=1003, title="ＦＬＯＷＥＲ", artist="test"),
                    1004: SongData(id=1004, title="對立", artist="test"),
                    1005: SongData(id=1005, title="Blue Noise", artist="Sakuzyo"),
                    1006: SongData(id=1006, title="Red Noise", artist="Other"),
                    1007: SongData(id=1007, title="Cyber Sparks", artist="削除"),
                    1008: SongData(id=1008, title="Starlight Disco", artist="DJ Sharpnel"),
                    1009: SongData(id=1009, title="Moonlight Sonata", artist="Ludwig"),
                    1010: SongData(id=1010, title="Night of Knights", artist="beatMARIO"),
                    1011: SongData(id=1011, title="Bad Apple!! feat. nomico", artist="Alstroemeria Records"),
                    1012: SongData(id=1012, title="Freedom Dive", artist="xi"),
                    1013: SongData(id=1013, title="World Vanquisher", artist="void"),
                    1014: SongData(id=1014, title="Invisible Frenzy", artist="t+pazolite"),
                    1015: SongData(id=1015, title="千本樱", artist="黒うさP"),
                    1016: SongData(id=1016, title="Lemon", artist="Kenshi Yonezu"),
                    1017: SongData(id=1017, title="Ｆｏｏ－Ｂａｒ", artist="a"),
                    1018: SongData(id=1018, title="Foo Bar", artist="b"),
                }
            }
            self.aliases_by_game: dict[str, dict[int, list[str]]] = {}
            self.aliases_by_game["quality"] = {
                song_id: [song.title]
                for song_id, song in self.songs_by_game["quality"].items()
            }
            self.aliases_by_game["quality"][1015].append("Senbonzakura")
            self.aliases_by_game["quality"][1016].append("Lemon")

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
    monkeypatch.setattr(lxns_client.catalog, "search_song", _Catalog().search_song)

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
    assert row["results"][0]["artist"] == "test"
    assert row["top_song_id"] == 1002
    assert row["top_match_type"] == "fuzzy_title"
    assert row["top_score"] == 99.0
    assert row["is_suspicious"] is True
    assert row["alias_candidate"]["alias"] == "eris"
    assert row["alias_candidate"]["song_id"] == 1002


@pytest.mark.asyncio
async def test_song_search_audit_defaults_to_suspicious_only(quality_search, monkeypatch, tmp_path: Path):
    from src.plugins.chiffon_bot.shared.search.catalog_search import search_song_with_audit
    from src.plugins.chiffon_bot.integrations.lxns.client import lxns_client

    class _Catalog:
        async def search_song(self, game_code: str, query: str | int):
            return await quality_search.search_song(query, game_code=game_code)

    audit_path = tmp_path / "song-search-history.jsonl"
    monkeypatch.delenv("SONG_SEARCH_AUDIT_LOG", raising=False)
    monkeypatch.setenv("SONG_SEARCH_AUDIT_PATH", str(audit_path))
    monkeypatch.setattr(lxns_client.catalog, "search_song", _Catalog().search_song)

    await search_song_with_audit("flower", game_code="quality")
    assert not audit_path.exists()

    await search_song_with_audit("eris", game_code="quality")
    rows = [
        json.loads(line)
        for line in audit_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert len(rows) == 1
    assert rows[0]["query"] == "eris"
    assert rows[0]["is_suspicious"] is True


def test_song_search_audit_updates_alias_candidate_status(tmp_path: Path):
    from src.plugins.chiffon_bot.shared.search.search_audit import (
        list_alias_candidates,
        update_alias_candidate_status,
    )

    history_path = tmp_path / "history.jsonl"
    history_path.write_text(
        json.dumps({
            "schema_version": 1,
            "game": "quality",
            "query": "eris",
            "trace_id": "eris:test",
            "top_match_type": "fuzzy_title",
            "top_score": 99.0,
            "alias_candidate": {
                "alias": "eris",
                "song_id": 1002,
                "title": "ERIS -Legend of Gaidelia-",
                "confidence": 0.99,
                "source": "search_audit",
                "status": "pending",
            },
            "results": [],
        }, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    assert len(list_alias_candidates(path=history_path)) == 1

    candidate = update_alias_candidate_status(
        1,
        "accepted",
        reviewer="10000",
        path=history_path,
    )

    assert candidate["status"] == "accepted"
    assert not list_alias_candidates(path=history_path)
    assert list_alias_candidates(status="accepted", path=history_path)[0]["alias"] == "eris"


def test_song_search_audit_skips_pending_for_accepted_alias(monkeypatch, tmp_path: Path):
    from src.plugins.chiffon_bot.shared.search.search_audit import record_search_history

    history_path = tmp_path / "history.jsonl"
    history_path.write_text(
        json.dumps({
            "schema_version": 1,
            "game": "quality",
            "query": "eris",
            "trace_id": "eris:accepted",
            "top_match_type": "fuzzy_title",
            "top_score": 99.0,
            "alias_candidate": {
                "alias": "eris",
                "song_id": 1002,
                "title": "ERIS -Legend of Gaidelia-",
                "confidence": 0.99,
                "source": "search_audit",
                "status": "accepted",
            },
            "results": [],
        }, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SONG_SEARCH_AUDIT_PATH", str(history_path))
    monkeypatch.delenv("SONG_SEARCH_AUDIT_LOG", raising=False)

    record_search_history(
        query="eris",
        game_code="quality",
        trace_id="eris:again",
        results=[
            SimpleNamespace(
                song_id=1002,
                title="ERIS -Legend of Gaidelia-",
                match_type=SimpleNamespace(value="fuzzy_title"),
                match_score=99.0,
                matched_text="ERIS -Legend of Gaidelia-",
            )
        ],
        duration_ms=1.0,
    )

    rows = [
        json.loads(line)
        for line in history_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(rows) == 2
    assert rows[-1]["alias_candidate"] is None


def test_song_search_audit_always_records_embedding_match(monkeypatch, tmp_path: Path):
    from src.plugins.chiffon_bot.shared.search.search_audit import record_search_history

    audit_path = tmp_path / "history.jsonl"
    monkeypatch.delenv("SONG_SEARCH_AUDIT_LOG", raising=False)
    monkeypatch.setenv("SONG_SEARCH_AUDIT_PATH", str(audit_path))

    record_search_history(
        query="semantic blue",
        game_code="quality",
        trace_id="embedding:test",
        results=[
            SimpleNamespace(
                song_id=1005,
                title="Blue Noise",
                match_type=SimpleNamespace(value="embedding"),
                match_score=95.0,
                matched_text="semantic blue",
                song_data=SimpleNamespace(artist="Sakuzyo"),
            )
        ],
        duration_ms=1.0,
    )

    rows = [
        json.loads(line)
        for line in audit_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(rows) == 1
    assert rows[0]["top_match_type"] == "embedding"
    assert rows[0]["top_score"] == 95.0


def test_song_search_audit_disabled_suppresses_embedding_match(monkeypatch, tmp_path: Path):
    from src.plugins.chiffon_bot.shared.search.search_audit import record_search_history

    audit_path = tmp_path / "history.jsonl"
    monkeypatch.setenv("SONG_SEARCH_AUDIT_LOG", "0")
    monkeypatch.setenv("SONG_SEARCH_AUDIT_PATH", str(audit_path))

    record_search_history(
        query="semantic blue",
        game_code="quality",
        trace_id="embedding:test",
        results=[
            SimpleNamespace(
                song_id=1005,
                title="Blue Noise",
                match_type=SimpleNamespace(value="embedding"),
                match_score=95.0,
                matched_text="semantic blue",
                song_data=SimpleNamespace(artist="Sakuzyo"),
            )
        ],
        duration_ms=1.0,
    )

    assert not audit_path.exists()


def test_song_search_eval_emits_alias_candidates(tmp_path: Path):
    history_path = tmp_path / "history.jsonl"
    history_path.write_text(
        json.dumps({
            "schema_version": 1,
            "game": "quality",
            "query": "eris",
            "trace_id": "eris:test",
            "top_match_type": "fuzzy_title",
            "top_score": 99.0,
            "alias_candidate": {
                "alias": "eris",
                "song_id": 1002,
                "title": "ERIS -Legend of Gaidelia-",
                "confidence": 0.99,
                "source": "search_audit",
                "status": "pending",
            },
            "results": [],
        }, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            "tools/song_search_eval.py",
            str(history_path),
            "--alias-candidates",
            "--format",
            "json",
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    rows = [
        json.loads(line)
        for line in completed.stdout.splitlines()
        if line.strip()
    ]
    assert rows
    assert rows[0]["alias"] == "eris"
    assert rows[0]["song_id"] == 1002
    assert rows[0]["status"] == "pending"


def test_song_search_eval_summary_groups_by_match_type(tmp_path: Path):
    history_path = tmp_path / "history.jsonl"
    history_path.write_text(
        "\n".join([
            json.dumps({
                "schema_version": 1,
                "game": "quality",
                "query": "semantic blue",
                "top_match_type": "embedding",
                "top_score": 95.0,
                "expected_top_id": 1005,
                "results": [
                    {"song_id": 1005, "title": "Blue Noise", "match_type": "embedding", "score": 95.0}
                ],
            }, ensure_ascii=False),
            json.dumps({
                "schema_version": 1,
                "game": "quality",
                "query": "eris",
                "top_match_type": "fuzzy_title",
                "top_score": 99.0,
                "expected_top_id": 1002,
                "results": [
                    {"song_id": 1002, "title": "ERIS -Legend of Gaidelia-", "match_type": "fuzzy_title", "score": 99.0}
                ],
            }, ensure_ascii=False),
        ]) + "\n",
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            "tools/song_search_eval.py",
            str(history_path),
            "--summary",
            "--format",
            "json",
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    summary = json.loads(completed.stdout)
    assert summary["total"] == 2
    assert summary["match_types"]["embedding"]["count"] == 1
    assert summary["match_types"]["fuzzy_title"]["avg_score"] == 99.0


def test_song_search_eval_summary_defaults_to_all_rows(tmp_path: Path):
    history_path = tmp_path / "history.jsonl"
    rows = [
        {
            "schema_version": 1,
            "game": "quality",
            "query": f"query-{index}",
            "top_match_type": "exact_title",
            "top_score": 100.0,
            "results": [
                {"song_id": index, "title": f"Song {index}", "match_type": "exact_title", "score": 100.0}
            ],
        }
        for index in range(60)
    ]
    history_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            "tools/song_search_eval.py",
            str(history_path),
            "--summary",
            "--format",
            "json",
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert json.loads(completed.stdout)["total"] == 60


@pytest.mark.asyncio
async def test_normalized_exact_title_match_type(quality_search):
    from arcade_helper.search import MatchType

    results = await quality_search.search_song("flower", game_code="quality")

    assert results
    assert results[0].song_id == 1003
    assert results[0].match_type is MatchType.EXACT_TITLE


@pytest.mark.asyncio
async def test_bm25_artist_title_query(quality_search):
    from arcade_helper.search import MatchType

    results = await quality_search.search_song("sakuzyo noise", game_code="quality")

    assert results
    assert results[0].song_id == 1005
    assert results[0].match_type is MatchType.BM25


@pytest.mark.asyncio
async def test_short_ascii_query_keeps_token_boundary_path(quality_search):
    from arcade_helper.search import MatchType

    results = await quality_search.search_song("eris", game_code="quality")

    assert results
    assert results[0].song_id == 1002
    assert results[0].match_type is MatchType.FUZZY_TITLE


@pytest.mark.asyncio
async def test_pinyin_initials_use_fieldized_index(quality_search):
    from arcade_helper.search import MatchType

    results = await quality_search.search_song("qby", game_code="quality")

    assert results
    assert results[0].song_id == 1015
    assert results[0].match_type is MatchType.PINYIN_INITIALS


@pytest.mark.asyncio
async def test_romaji_alias_match_type(quality_search):
    from arcade_helper.search import MatchType

    results = await quality_search.search_song("senbon", game_code="quality")

    assert results
    assert results[0].song_id == 1015
    assert results[0].match_type is MatchType.ROMAJI


@pytest.mark.asyncio
async def test_single_token_query_does_not_short_circuit_to_bm25(quality_search):
    from arcade_helper.search import MatchType

    results = await quality_search.search_song("summer", game_code="quality")

    assert results
    assert results[0].song_id == 1001
    assert results[0].match_type is not MatchType.BM25


@pytest.mark.asyncio
async def test_short_ascii_query_does_not_hit_romaji_partial(quality_search):
    from arcade_helper.search import MatchType

    results = await quality_search.search_song("lem", game_code="quality")

    assert not results or results[0].match_type is not MatchType.ROMAJI


@pytest.mark.asyncio
async def test_normalized_title_collision_returns_all_candidates(quality_search):
    from arcade_helper.search.song_query import _query_song_by_normalized_exact, _repository_var

    token = _repository_var.set(quality_search.repository)
    try:
        results = await _query_song_by_normalized_exact("foo bar", game_code="quality")
    finally:
        _repository_var.reset(token)
    result_ids = [result.song_id for result in results]

    assert 1017 in result_ids
    assert 1018 in result_ids


@pytest.mark.asyncio
async def test_search_index_cache_invalidates_with_alias_cache(quality_search):
    from arcade_helper.search import MatchType
    from arcade_helper.core.song import SongData
    from arcade_helper.search.song_query import invalidate_alias_cache

    await quality_search.search_song("flower", game_code="quality")
    quality_search.repository.songs_by_game["quality"][1003] = SongData(
        id=1003,
        title="ＳＴＡＲ",
        artist="test",
    )

    invalidate_alias_cache("quality")
    results = await quality_search.search_song("star", game_code="quality")

    assert results
    assert results[0].song_id == 1003
    assert results[0].match_type is MatchType.EXACT_TITLE


@pytest.mark.asyncio
async def test_embedding_fallback_is_disabled_by_default(quality_search, monkeypatch, tmp_path: Path):
    monkeypatch.delenv("SONG_SEARCH_EMBEDDING_ENABLED", raising=False)
    embedding_path = tmp_path / "embeddings.jsonl"
    embedding_path.write_text(
        "\n".join([
            json.dumps({"game": "quality", "query": "zzzz semantic", "vector": [1, 0]}),
            json.dumps({"game": "quality", "song_id": 1005, "vector": [1, 0]}),
        ]) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SONG_SEARCH_EMBEDDING_PATH", str(embedding_path))

    assert await quality_search.search_song("zzzz semantic", game_code="quality") == []


@pytest.mark.asyncio
async def test_embedding_fallback_returns_local_vector_match(quality_search, monkeypatch, tmp_path: Path):
    from arcade_helper.search import MatchType

    embedding_path = tmp_path / "embeddings.jsonl"
    embedding_path.write_text(
        "\n".join([
            json.dumps({"game": "quality", "query": "zzzz semantic", "vector": [1, 0]}),
            json.dumps({"game": "quality", "song_id": 1005, "vector": [1, 0]}),
            json.dumps({"game": "quality", "song_id": 1006, "vector": [0, 1]}),
        ]) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SONG_SEARCH_EMBEDDING_ENABLED", "1")
    monkeypatch.setenv("SONG_SEARCH_EMBEDDING_PATH", str(embedding_path))
    monkeypatch.setenv("SONG_SEARCH_EMBEDDING_THRESHOLD", "90")

    results = await quality_search.search_song("zzzz semantic", game_code="quality")

    assert results
    assert results[0].song_id == 1005
    assert results[0].match_type is MatchType.EMBEDDING


@pytest.mark.asyncio
async def test_embedding_fallback_does_not_override_exact_match(quality_search, monkeypatch, tmp_path: Path):
    from arcade_helper.search import MatchType

    embedding_path = tmp_path / "embeddings.jsonl"
    embedding_path.write_text(
        "\n".join([
            json.dumps({"game": "quality", "query": "Blue Noise", "vector": [1, 0]}),
            json.dumps({"game": "quality", "song_id": 1005, "vector": [0, 1]}),
            json.dumps({"game": "quality", "song_id": 1006, "vector": [1, 0]}),
        ]) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SONG_SEARCH_EMBEDDING_ENABLED", "1")
    monkeypatch.setenv("SONG_SEARCH_EMBEDDING_PATH", str(embedding_path))
    monkeypatch.setenv("SONG_SEARCH_EMBEDDING_THRESHOLD", "90")

    results = await quality_search.search_song("Blue Noise", game_code="quality")

    assert results
    assert results[0].song_id == 1005
    assert results[0].match_type is MatchType.EXACT_TITLE
