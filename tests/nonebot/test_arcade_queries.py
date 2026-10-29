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


async def _import_song(game, *, title="FLOWER", artist="xi", aliases=(), native="1001"):
    from arcade_helper.catalog import CatalogRecord
    from arcade_helper.aliases import AliasObservation
    from src.plugins.chiffon_bot.integrations.lxns.client import lxns_client
    song = SongData(id=int(native), title=title, artist=artist,
                    alias_observations=[AliasObservation(source_key=f"lxns:{game}", text=a) for a in aliases])
    report = await lxns_client.identities.import_records(game, [CatalogRecord(song, song.model_dump(mode="json"), native)],
                                                        provider="catalog", namespace="native", complete=False)
    return report.song_ids[native]


async def test_arcade_games_command_searches_imported_catalog(app, seeded_song_db, monkeypatch):
    from src.plugins.chiffon_bot.app.commands import arcade
    song_id = await _import_song("sdvx")
    responses = []
    _finish_capture(monkeypatch, arcade, responses)
    await _dispatch(app, "/arcade.games FLOWER", 1, _find_matcher(arcade, "_games"))
    assert responses[0].text == f"《FLOWER》在 1 个游戏中找到，共 1 条曲目记录：\n[sdvx] [{song_id}] FLOWER"


async def test_arcade_list_command_lists_queryable_game_codes(
    app, loaded_chiffon_bot, monkeypatch
):
    from src.plugins.chiffon_bot.app.commands import arcade

    responses = []
    _finish_capture(monkeypatch, arcade, responses)

    async def fake_sites():
        return [
            {"gameCode": "maimai"},
            {"gameCode": "SDVX"},
            {"gameCode": "sdvx"},
            {"gameCode": "any"},
            {"gameCode": "ongeki"},
        ]

    monkeypatch.setattr(arcade.lxns_client.data.catalog.arcade_songs, "sites", fake_sites)

    await _dispatch(app, "/arcade.list", 7, _find_matcher(arcade, "_list"))

    assert len(responses) == 1
    assert responses[0].text == (
        "arcade-songs 可查询游戏（3 个）：\n[maimai]\n[sdvx]\n[ongeki]"
    )


async def test_arcade_command_blocks_lower_priority_but_unknown_command_propagates(
    app, loaded_chiffon_bot, monkeypatch,
):
    from nonebot import on_message
    from src.plugins.chiffon_bot.app.commands import arcade

    responses, propagated = [], []
    _finish_capture(monkeypatch, arcade, responses)
    sentinel = on_message(priority=12, block=False)

    @sentinel.handle()
    async def record(event: GroupMessageEvent):
        propagated.append(event.get_plaintext())

    async with app.test_matcher([_find_matcher(arcade, "_help"), sentinel]) as ctx:
        adapter = ctx.create_adapter(base=Adapter)
        bot = ctx.create_bot(base=Bot, adapter=adapter, self_id="10000")
        ctx.receive_event(bot, _group_event("/arcade.help", 901))
        ctx.receive_event(bot, _group_event("/arcade.unknown", 902))
    assert len(responses) == 1
    assert propagated == ["/arcade.unknown"]
    sentinel.destroy()


async def test_arcade_help_is_text_overview_without_catalog_access(
    app, loaded_chiffon_bot, monkeypatch
):
    from src.plugins.chiffon_bot.app.commands import arcade

    responses = []
    _finish_capture(monkeypatch, arcade, responses)

    async def unavailable_sites():
        raise AssertionError("帮助总览不应请求远端游戏列表")

    monkeypatch.setattr(arcade.lxns_client.data.catalog.arcade_songs, "sites", unavailable_sites)
    await _dispatch(app, "/arcade.help", 8, _find_matcher(arcade, "_help"))

    assert len(responses) == 1
    response = responses[0]
    assert response.image is None
    assert response.reply_to == 8
    for feature in ("maimai", "CHUNITHM", "B50/R50", "随机选曲", "曲绘识别", "趋势图"):
        assert feature in response.text
    for command in ("/arcade.list", "/mai.help", "/chuni.help", "/arcade.song",
                    "/arcade.artist", "/arcade.alias", "/arcade.games", "/acc help", "/event.help"):
        assert command in response.text
    assert "需先导入曲库" in response.text
    assert "SUPERUSER" in response.text


async def test_arcade_games_alias_expands_confirmed_work_only(app, seeded_song_db, monkeypatch):
    from src.plugins.chiffon_bot.app.commands import arcade
    source = await _import_song("sdvx", aliases=["flower nickname"])
    linked = await _import_song("ongeki")
    unrelated = await _import_song("iidx", artist="different artist")
    responses = []
    _finish_capture(monkeypatch, arcade, responses)
    await _dispatch(app, "/arcade.games flower nickname", 6, _find_matcher(arcade, "_games"))
    assert f"[sdvx] [{source}] FLOWER" in responses[0].text
    assert f"[ongeki] [{linked}] FLOWER" in responses[0].text
    assert f"[iidx] [{unrelated}]" not in responses[0].text
    await _dispatch(app, "/arcade.games FLOWER", 8, _find_matcher(arcade, "_games"))
    from arcade_helper.storage.tortoise.catalog_models import GameSong
    for song in await GameSong.filter(id__in=[source, linked, unrelated]):
        assert str(song.work_id) not in responses[-1].text
    assert f"[iidx] [{unrelated}] FLOWER（作品 1）" in responses[-1].text
    assert f"[ongeki] [{linked}] FLOWER（作品 2）" in responses[-1].text
    assert f"[sdvx] [{source}] FLOWER（作品 2）" in responses[-1].text


async def test_arcade_games_ignores_legacy_jsonl_overlay(app, seeded_song_db, monkeypatch, tmp_path):
    from src.plugins.chiffon_bot.app.commands import arcade
    await _import_song("sdvx")
    path = tmp_path / "aliases.jsonl"
    path.write_text(json.dumps({"game": "sdvx", "query": "retired nickname", "alias_candidate": {
        "alias": "retired nickname", "song_id": 1001, "title": "FLOWER", "status": "accepted"}}) + "\n", encoding="utf-8")
    monkeypatch.setenv("SONG_SEARCH_AUDIT_PATH", str(path))
    responses = []
    _finish_capture(monkeypatch, arcade, responses)
    await _dispatch(app, "/arcade.games retired nickname", 5, _find_matcher(arcade, "_games"))
    assert "在 1 个游戏中找到" not in responses[0].text


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

    async def fake_load_search_songs(game_code: str):
        assert game_code == "sdvx"
        return songs

    monkeypatch.setattr(arcade.lxns_client.catalog, "load_search_songs", fake_load_search_songs)
    async def forbid_full_catalog(*args):
        raise AssertionError("Artist query must not load chart payloads")
    monkeypatch.setattr(arcade.lxns_client.catalog, "load_all_songs", forbid_full_catalog)

    await _dispatch(app, "/arcade.artist sdvx xi", 2, _find_matcher(arcade, "_artist"))

    assert len(responses) == 1
    assert responses[0].text == (
        "[sdvx] 曲师名包含“xi”的歌曲（2 首）：\n"
        "[1002] CROSS\n[1001] FLOWER"
    )


async def test_natural_language_song_games_query_returns_catalog_hit(app, seeded_song_db, monkeypatch):
    from src.plugins.chiffon_bot.app.commands import arcade, natural_language
    song_id = await _import_song("sdvx")
    responses = []
    _finish_capture(monkeypatch, natural_language, responses)
    async def fake_ack(*_args, **_kwargs):
        pass
    monkeypatch.setattr(natural_language, "ack_message", fake_ack)
    await _dispatch(app, "FLOWER在哪些游戏里？", 3, _find_matcher(natural_language, "handle_cross_game_song_query"))
    assert f"[sdvx] [{song_id}] FLOWER" in responses[0].text


async def test_natural_language_artist_query_returns_matching_songs(
    app, loaded_chiffon_bot, monkeypatch
):
    from src.plugins.chiffon_bot.app.commands import arcade, natural_language

    responses = []
    _finish_capture(monkeypatch, natural_language, responses)

    async def fake_ack(*_args, **_kwargs):
        return None

    async def fake_load_search_songs(game_code: str):
        assert game_code == "sdvx"
        return {1001: SongData(id=1001, title="FLOWER", artist="xi")}

    monkeypatch.setattr(natural_language, "ack_message", fake_ack)
    monkeypatch.setattr(arcade.lxns_client.catalog, "load_search_songs", fake_load_search_songs)

    await _dispatch(
        app,
        "xi在sdvx里有哪些歌？",
        4,
        _find_matcher(natural_language, "handle_cross_game_song_query"),
    )

    assert len(responses) == 1
    assert responses[0].text == "[sdvx] 曲师名包含“xi”的歌曲（1 首）：\n[1001] FLOWER"


async def test_native_source_only_queries_keep_catalog_and_native_ids_separate(app, seeded_song_db, monkeypatch):
    from arcade_helper.games.chunithm.schemas import ChuniSongData
    from src.plugins.chiffon_bot.integrations.lxns.client import lxns_client
    from src.plugins.chiffon_bot.app.commands import arcade, natural_language
    from src.plugins.chiffon_bot.shared.handlers import generic_song_info as info

    await lxns_client.data.catalog.sync_songs("chunithm", {
        7: ChuniSongData(id=7, title="Known CH", artist="Artist"),
    }, supplemental_provider="arcade_songs", supplemental_payload={"songs": [
        {"songId": "known", "title": "Known CH", "artist": "Artist", "sheets": []},
        {"songId": "Melodiniq", "title": "Melodiniq", "artist": "onoken", "version": "X-VERSE-X",
         "sheets": [{"type": "std", "difficulty": "master", "level": "15+", "internalLevelValue": 15.6}]},
    ]})
    candidate, = (await lxns_client.catalog.search_all("Melodiniq")).candidates
    internal = candidate.game_song_id
    assert await lxns_client.catalog.public_song_id("chunithm", internal) == f"catalog:{internal}"
    await lxns_client.data.catalog.sync_songs("chunithm", {
        internal: ChuniSongData(id=internal, title="Native ID collision", artist="Other"),
    })
    numeric, = await lxns_client.catalog.search_song("chunithm", str(internal))
    assert numeric.title == "Native ID collision"
    explicit, = await lxns_client.catalog.search_song("chunithm", f"catalog:{internal}")
    assert explicit.title == "Melodiniq" and explicit.song_data.catalog_only
    assert (await lxns_client.catalog.alias_candidate_result(candidate)).song_data.catalog_only

    async def no_jacket(*args, **kwargs):
        return None
    monkeypatch.setattr(info, "load_song_jacket_bytes", no_jacket)
    monkeypatch.setattr(arcade, "load_song_jacket_bytes", no_jacket)
    # The ordinary native renderer and score/collection APIs must not see an internal ID.
    class Adapter:
        game_code = "chunithm"
        display_name = "中二"
        async def fetch_collections(self, *args):
            raise AssertionError("catalog ID must not be used as a native ID")
        async def render_song_image(self, *args):
            raise AssertionError("source-only metadata requires the generic display")
    adapter = Adapter()
    monkeypatch.setattr(natural_language, "iter_searchable_adapters", lambda: [adapter])
    response = await natural_language._query_alias_song("Melodiniq", _group_event("Melodiniq是什么歌", 99))
    assert "Melodiniq" in response.text and f"catalog:{internal}" in response.text and "15.6" in response.text
    scoped = await arcade.query_arcade_song("chunithm", "Melodiniq", 100)
    assert "Melodiniq" in scoped.text and f"catalog:{internal}" in scoped.text
    result = await info.generic_song_info("Melodiniq", "user", 101, adapter)
    assert "暂无原生 ID" in result.text
