from __future__ import annotations

import pytest


def test_extract_arcade_song_query_parses_chage_form():
    from src.plugins.chiffon_bot.app.commands.natural_language import (
        _extract_arcade_song_query,
    )

    assert _extract_arcade_song_query("查歌 sdvx FLOWER") == ("sdvx", "FLOWER")
    assert _extract_arcade_song_query("查歌 ONGEKI モンダイナイトリッパー！") == (
        "ongeki",
        "モンダイナイトリッパー！",
    )
    assert _extract_arcade_song_query("查歌 sdvx") is None
    assert _extract_arcade_song_query("查歌  FLOWER") is None
    assert _extract_arcade_song_query("sdvx FLOWER是什么歌") is None


def test_extract_arcade_song_query_rejects_unknown_game_code():
    from src.plugins.chiffon_bot.app.commands.natural_language import (
        _extract_arcade_song_query,
    )

    assert _extract_arcade_song_query(
        "查歌 sdvx FLOWER", valid_codes={"sdvx", "ongeki"}
    ) == ("sdvx", "FLOWER")
    assert (
        _extract_arcade_song_query("查歌 maimai 系ぎて", valid_codes={"sdvx"}) is None
    )


def test_extract_arcade_song_query_skips_filtering_when_codes_unknown():
    from src.plugins.chiffon_bot.app.commands.natural_language import (
        _extract_arcade_song_query,
    )

    assert _extract_arcade_song_query("查歌 anything 歌名", valid_codes=None) == (
        "anything",
        "歌名",
    )


@pytest.mark.asyncio
async def test_known_arcade_song_codes_extracts_game_codes(monkeypatch):
    from src.plugins.chiffon_bot.app.commands import natural_language as module

    async def fake_sites():
        return [
            {"gameCode": "SDVX"},
            {"gameCode": "ongeki"},
            {"name": "no-code"},
            "not-a-dict",
        ]

    monkeypatch.setattr(
        module.lxns_client.data.catalog.arcade_songs, "sites", fake_sites
    )

    assert await module._known_arcade_song_codes() == {"sdvx", "ongeki"}


@pytest.mark.asyncio
async def test_known_arcade_song_codes_returns_none_on_failure(monkeypatch):
    from src.plugins.chiffon_bot.app.commands import natural_language as module

    async def failing_sites():
        raise RuntimeError("boom")

    monkeypatch.setattr(
        module.lxns_client.data.catalog.arcade_songs, "sites", failing_sites
    )

    assert await module._known_arcade_song_codes() is None
