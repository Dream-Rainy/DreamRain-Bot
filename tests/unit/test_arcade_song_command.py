from __future__ import annotations

from typing import ClassVar

import pytest
from arcade_helper.core.song import SongData, SongSheet
from arcade_helper.search import MatchType, SongQueryResult


def test_parse_arcade_song_args():
    from src.plugins.chiffon_bot.app.commands.arcade import parse_arcade_song_args

    assert parse_arcade_song_args("sdvx FLOWER") == ("sdvx", "FLOWER")
    assert parse_arcade_song_args("  ONGEKI   モンダイナイトリッパー！ ") == (
        "ongeki",
        "モンダイナイトリッパー！",
    )
    assert parse_arcade_song_args("sdvx") is None


def test_format_arcade_song_detail():
    from src.plugins.chiffon_bot.shared.handlers.song_text import (
        format_song_text_detail,
    )

    assert format_song_text_detail("maimai", _song_result()) == [
        "[maimai] 曲目详情",
        "曲名: モンダイナイトリッパー！ (1498)",
        "艺术家: 名取さな",
        "分类: POPSアニメ",
        "BPM: 180",
        "版本: 舞萌DX 2023",
        "备注: さなちゃんねる区域",
        "定数 (DX): 4.0 / 7.0 / 10.7 / 13.6",
    ]


@pytest.mark.asyncio
async def test_arcade_song_response_downloads_jacket(monkeypatch):
    from src.plugins.chiffon_bot.app.commands.arcade import build_arcade_song_response

    called = []

    async def fake_get_bytes(url: str):
        called.append(url)
        return b"jacket"

    monkeypatch.setattr("src.plugins.chiffon_bot.shared.handlers.song_text.http_client.get_bytes", fake_get_bytes)

    result = _song_result(image_name="jacket.png")
    response = await build_arcade_song_response(
        "sdvx",
        [result],
        123,
        arcade_sites=[{"gameCode": "sdvx", "dataSourceUrl": "https://example.test/sdvx"}],
    )

    assert called == ["https://example.test/sdvx/jacket.png"]
    assert response.image == b"jacket"
    assert response.text and "曲名: モンダイナイトリッパー！ (1498)" in response.text


@pytest.mark.asyncio
async def test_arcade_song_response_uses_cloudfront_cover_path(monkeypatch):
    from src.plugins.chiffon_bot.app.commands.arcade import build_arcade_song_response

    called = []

    async def fake_get_bytes(url: str):
        called.append(url)
        return b"jacket"

    monkeypatch.setattr("src.plugins.chiffon_bot.shared.handlers.song_text.http_client.get_bytes", fake_get_bytes)

    result = _song_result(image_name="58e53aa7c9a319f198a4598c18e577a8481689fe1774e81659a30cf4fe71d57d.png")
    response = await build_arcade_song_response(
        "sdvx",
        [result],
        123,
        arcade_sites=[{"gameCode": "sdvx", "dataSourceUrl": "https://dp4p6x0xfi5o9.cloudfront.net/sdvx"}],
    )

    assert called == [
        "https://dp4p6x0xfi5o9.cloudfront.net/sdvx/img/cover/"
        "58e53aa7c9a319f198a4598c18e577a8481689fe1774e81659a30cf4fe71d57d.png"
    ]
    assert response.image == b"jacket"


@pytest.mark.asyncio
async def test_query_arcade_song_uses_audited_search(monkeypatch):
    from src.plugins.chiffon_bot.app.commands import arcade as module

    result = _song_result()
    calls = []

    async def fake_search(query, *, game_code: str):
        calls.append((game_code, query))
        return [result]

    async def fake_sites():
        return []

    async def fake_build(game_code, results, message_id, *, arcade_sites=None):
        assert game_code == "sdvx"
        assert results == [result]
        assert message_id == 123
        assert arcade_sites == []
        return module.BotResponse(text="ok", reply_to=message_id)

    monkeypatch.setattr(module, "search_song_with_audit", fake_search)
    monkeypatch.setattr(module.lxns_client.data.catalog.arcade_songs, "sites", fake_sites)
    monkeypatch.setattr(module, "build_arcade_song_response", fake_build)

    response = await module.query_arcade_song("sdvx", "FLOWER", 123)

    assert response.text == "ok"
    assert calls == [("sdvx", "FLOWER")]


@pytest.mark.asyncio
async def test_generic_song_info_falls_back_to_text(monkeypatch):
    from src.plugins.chiffon_bot.shared.handlers import generic_song_info as module

    result = _song_result(image_name="")

    async def fake_search(*args, **kwargs):
        return [result]

    async def fake_load_jacket(*args, **kwargs):
        return b"jacket"

    class Adapter:
        game_code = "maimai"
        display_name = "maimai"

        async def fetch_collections(self, song_id: int):
            return []

        async def render_song_image(self, song_data):
            raise RuntimeError("boom")

    monkeypatch.setattr(module, "search_song_with_audit", fake_search)
    monkeypatch.setattr(module, "load_song_jacket_bytes", fake_load_jacket)

    response = await module.generic_song_info("1498", "user", 123, Adapter())

    assert response.image == b"jacket"
    assert response.text and response.text.startswith("图片渲染失败，已改用文本结果。")
    assert "曲名: モンダイナイトリッパー！ (1498)" in response.text


def _song_result(*, image_name: str = "") -> SongQueryResult:
    song = SongData(
        id=1498,
        title="モンダイナイトリッパー！",
        artist="名取さな",
        bpm=180,
        image_name=image_name,
        category="POPSアニメ",
        version="舞萌DX 2023",
        comment="さなちゃんねる区域",
        difficulties={
            "dx": [
                SongSheet(type="dx", difficulty="basic", level="4", internal_level_value=4.0),
                SongSheet(type="dx", difficulty="advanced", level="7", internal_level_value=7.0),
                SongSheet(type="dx", difficulty="expert", level="10+", internal_level_value=10.7),
                SongSheet(type="dx", difficulty="master", level="13+", internal_level_value=13.6),
            ]
        },
    )
    return SongQueryResult(
        song_id=1498,
        title=song.title,
        match_type=MatchType.EXACT_ID,
        match_score=100.0,
        matched_text="1498",
        song_data=song,
    )
