from __future__ import annotations

import json

from arcade_helper.core.song import SongData
from arcade_helper.search import MatchType, SongQueryResult
from nonebot.adapters.onebot.v11 import Adapter, Bot, GroupMessageEvent, Message
from nonebot.exception import FinishedException


def _group_event(text: str, message_id: int) -> GroupMessageEvent:
    return GroupMessageEvent(
        time=1,
        self_id=10000,
        post_type="message",
        sub_type="normal",
        user_id=123,
        message_type="group",
        message_id=message_id,
        message=Message(text),
        raw_message=text,
        font=0,
        sender={"user_id": 123, "nickname": "tester"},
        group_id=456,
    )


def _find_matcher(module, handler_name: str):
    from nonebot.matcher import matchers

    candidates = [
        matcher
        for registered in matchers.values()
        for matcher in registered
        if any(
            handler.call.__name__ == handler_name
            and handler.call.__globals__ is module.__dict__
            for handler in matcher.handlers
        )
    ]
    assert len(candidates) == 1
    return candidates[0]


async def _dispatch(app, text: str, message_id: int, matcher) -> None:
    async with app.test_matcher(matcher) as ctx:
        adapter = ctx.create_adapter(base=Adapter)
        bot = ctx.create_bot(base=Bot, adapter=adapter, self_id="10000")
        ctx.receive_event(bot, _group_event(text, message_id))


def _finish_capture(monkeypatch, module, responses):
    async def finish(response):
        responses.append(response)
        raise FinishedException

    monkeypatch.setattr(module, "finish_with", finish)


def _song_result(
    *,
    song_id: int = 1001,
    title: str = "FLOWER",
    match_type: MatchType = MatchType.EXACT_TITLE,
    matched_text: str | None = None,
) -> SongQueryResult:
    song = SongData(id=song_id, title=title, artist="xi")
    return SongQueryResult(
        song_id=song.id,
        title=song.title,
        match_type=match_type,
        match_score=100.0,
        matched_text=matched_text or song.title,
        song_data=song,
    )


async def test_arcade_games_command_searches_site_catalogs(
    app, loaded_chiffon_bot, monkeypatch
):
    from src.plugins.chiffon_bot.app.commands import arcade

    responses = []
    _finish_capture(monkeypatch, arcade, responses)

    async def fake_sites():
        return [{"gameCode": "SDVX"}, {"gameCode": "ongeki"}]

    async def fake_search(query: str, *, game_code: str):
        return [_song_result()] if game_code == "sdvx" else []

    monkeypatch.setattr(arcade.lxns_client.data.catalog.arcade_songs, "sites", fake_sites)
    monkeypatch.setattr(arcade.lxns_client.catalog.search, "search_song", fake_search)

    await _dispatch(app, "/arcade.games FLOWER", 1, _find_matcher(arcade, "_games"))

    assert len(responses) == 1
    assert responses[0].text == "《FLOWER》在 1 个游戏中找到，共 1 条曲目记录：\n[sdvx] [1001] FLOWER"


async def test_arcade_games_command_expands_alias_across_games_and_skips_any(
    app, loaded_chiffon_bot, monkeypatch
):
    from src.plugins.chiffon_bot.app.commands import arcade

    responses = []
    _finish_capture(monkeypatch, arcade, responses)
    calls = []

    async def fake_sites():
        return [
            {"gameCode": "sdvx"},
            {"gameCode": "maimai"},
            {"gameCode": "any"},
        ]

    async def fake_search(query: str, *, game_code: str):
        calls.append((query, game_code))
        if query == "flower nickname" and game_code == "sdvx":
            return [
                _song_result(
                    match_type=MatchType.EXACT_ALIAS,
                    matched_text="flower nickname",
                )
            ]
        if query == "FLOWER" and game_code == "maimai":
            return [_song_result(song_id=2001)]
        return []

    monkeypatch.setattr(arcade.lxns_client.data.catalog.arcade_songs, "sites", fake_sites)
    monkeypatch.setattr(arcade.lxns_client.catalog.search, "search_song", fake_search)

    await _dispatch(app, "/arcade.games flower nickname", 6, _find_matcher(arcade, "_games"))

    assert len(responses) == 1
    assert responses[0].text == (
        "《flower nickname》在 2 个游戏中找到，共 2 条曲目记录：\n"
        "[sdvx] [1001] FLOWER\n[maimai] [2001] FLOWER"
    )
    assert ("FLOWER", "maimai") in calls
    assert all(game_code != "any" for _, game_code in calls)


async def test_arcade_games_command_matches_accepted_alias(
    app, loaded_chiffon_bot, monkeypatch, tmp_path
):
    from arcade_helper.search.song_query import invalidate_alias_cache
    from src.plugins.chiffon_bot.app.commands import arcade

    alias = "flower nickname"
    history_path = tmp_path / "aliases.jsonl"
    history_path.write_text(
        json.dumps(
            {
                "game": "sdvx",
                "query": alias,
                "alias_candidate": {
                    "alias": alias,
                    "song_id": 1001,
                    "title": "FLOWER",
                    "status": "accepted",
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SONG_SEARCH_AUDIT_PATH", str(history_path))
    song = SongData(id=1001, title="FLOWER", artist="xi")
    responses = []
    _finish_capture(monkeypatch, arcade, responses)

    async def fake_sites():
        return [{"gameCode": "sdvx"}]

    async def fake_catalog(game_code: str):
        assert game_code == "sdvx"
        return {song.id: song}

    monkeypatch.setattr(arcade.lxns_client.data.catalog.arcade_songs, "sites", fake_sites)
    monkeypatch.setattr(
        arcade.lxns_client.data.catalog.arcade_songs, "catalog", fake_catalog
    )
    invalidate_alias_cache("sdvx")
    try:
        await _dispatch(app, f"/arcade.games {alias}", 5, _find_matcher(arcade, "_games"))
    finally:
        invalidate_alias_cache("sdvx")

    assert len(responses) == 1
    assert responses[0].text == "《flower nickname》在 1 个游戏中找到，共 1 条曲目记录：\n[sdvx] [1001] FLOWER"


async def test_arcade_artist_command_returns_matching_songs(
    app, loaded_chiffon_bot, monkeypatch
):
    from src.plugins.chiffon_bot.app.commands import arcade

    responses = []
    _finish_capture(monkeypatch, arcade, responses)
    songs = {
        1001: SongData(id=1001, title="FLOWER", artist="xi"),
        1002: SongData(id=1002, title="CROSS", artist="xi & satella"),
        1003: SongData(id=1003, title="Other", artist="Camellia"),
    }

    async def fake_load_all_songs(game_code: str):
        assert game_code == "sdvx"
        return songs

    monkeypatch.setattr(arcade.lxns_client.catalog, "load_all_songs", fake_load_all_songs)

    await _dispatch(app, "/arcade.artist sdvx xi", 2, _find_matcher(arcade, "_artist"))

    assert len(responses) == 1
    assert responses[0].text == (
        "[sdvx] 曲师名包含“xi”的歌曲（2 首）：\n"
        "[1002] CROSS\n[1001] FLOWER"
    )


async def test_natural_language_song_games_query_returns_catalog_hit(
    app, loaded_chiffon_bot, monkeypatch
):
    from src.plugins.chiffon_bot.app.commands import arcade, natural_language

    responses = []
    _finish_capture(monkeypatch, natural_language, responses)

    async def fake_ack(*_args, **_kwargs):
        return None

    async def fake_sites():
        return [{"gameCode": "sdvx"}]

    async def fake_search(query: str, *, game_code: str):
        assert query == "FLOWER"
        assert game_code == "sdvx"
        return [_song_result()]

    monkeypatch.setattr(natural_language, "ack_message", fake_ack)
    monkeypatch.setattr(arcade.lxns_client.data.catalog.arcade_songs, "sites", fake_sites)
    monkeypatch.setattr(arcade.lxns_client.catalog.search, "search_song", fake_search)

    await _dispatch(
        app,
        "FLOWER在哪些游戏里？",
        3,
        _find_matcher(natural_language, "handle_cross_game_song_query"),
    )

    assert len(responses) == 1
    assert "[sdvx] [1001] FLOWER" in responses[0].text


async def test_natural_language_artist_query_returns_matching_songs(
    app, loaded_chiffon_bot, monkeypatch
):
    from src.plugins.chiffon_bot.app.commands import arcade, natural_language

    responses = []
    _finish_capture(monkeypatch, natural_language, responses)

    async def fake_ack(*_args, **_kwargs):
        return None

    async def fake_load_all_songs(game_code: str):
        assert game_code == "sdvx"
        return {1001: SongData(id=1001, title="FLOWER", artist="xi")}

    monkeypatch.setattr(natural_language, "ack_message", fake_ack)
    monkeypatch.setattr(arcade.lxns_client.catalog, "load_all_songs", fake_load_all_songs)

    await _dispatch(
        app,
        "xi在sdvx里有哪些歌？",
        4,
        _find_matcher(natural_language, "handle_cross_game_song_query"),
    )

    assert len(responses) == 1
    assert responses[0].text == "[sdvx] 曲师名包含“xi”的歌曲（1 首）：\n[1001] FLOWER"
