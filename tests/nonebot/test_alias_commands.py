"""Real adapter commands, persisted decisions and search-cache invalidation."""

import nonebot
import pytest

from arcade_helper.storage.tortoise.alias_models import AliasRequest, AliasEvidence
from nonebot.adapters.onebot.v11 import Adapter, Bot
from tests.nonebot.test_arcade_queries import _group_event, _find_matcher, _finish_capture, _import_song
from tests.fixtures.song_seed import MAI_SONG_ID


async def _dispatch(app, module, handler, text, message_id, user_id):
    async with app.test_matcher(_find_matcher(module, handler)) as ctx:
        bot = ctx.create_bot(base=Bot, adapter=ctx.create_adapter(base=Adapter), self_id="10000")
        event = _group_event(text, message_id).model_copy(update={"user_id": user_id})
        ctx.receive_event(bot, event)


async def test_native_alias_sync_uses_light_result_and_reports_real_count(app, seeded_song_db, monkeypatch):
    from types import SimpleNamespace
    from src.plugins.chiffon_bot.app.commands import alias
    from tests.fixtures.song_seed import MAI_SONG_TITLE

    monkeypatch.setattr(nonebot.get_driver().config, "superusers", {"456"})
    responses, calls = [], []
    _finish_capture(monkeypatch, alias, responses)
    async def sync(game, *, include_songs):
        assert include_songs is False
        calls.append(game)
        return SimpleNamespace(ok=True, songs=None)
    monkeypatch.setattr(alias.lxns_client.data.catalog, "sync_game_from_remote", sync)
    assert (await alias.lxns_client.data.catalog.load_song_index("maimai"))[MAI_SONG_ID] == MAI_SONG_TITLE
    matcher = _find_matcher(alias, "_admin_alias")
    async with app.test_matcher(matcher) as ctx:
        bot = ctx.create_bot(base=Bot, adapter=ctx.create_adapter(base=Adapter), self_id="10000")
        ctx.receive_event(bot, _group_event("/admin.alias sync maimai", 91))
        ctx.should_not_pass_permission(matcher)
    assert not calls and not responses
    await _dispatch(app, alias, "_admin_alias", "/admin.alias sync maimai", 92, 456)
    assert calls == ["maimai"]
    assert responses[-1].text == "曲库同步完成：maimai，1 首"


async def test_alias_submit_review_revoke_and_conflict(app, seeded_song_db, monkeypatch):
    from src.plugins.chiffon_bot.app.commands import alias
    client = alias.lxns_client
    monkeypatch.setattr(nonebot.get_driver().config, "superusers", {"456", "789"})
    responses = []
    _finish_capture(monkeypatch, alias, responses)
    text = f"/arcade.alias add maimai {MAI_SONG_ID} 待审简称"
    await _dispatch(app, alias, "_alias", text, 101, 123)
    await _dispatch(app, alias, "_alias", text, 101, 123)
    request = await AliasRequest.all().first()
    assert await AliasRequest.all().count() == 1
    assert request.actor_id != 123  # Adapter account IDs are not internal actors.
    assert request.payload["scope"] == "game_song"
    assert not (await client.data.aliases.resolve_alias("待审简称")).candidates
    await _dispatch(app, alias, "_alias", f"/arcade.alias request {request.id}", 107, 999)
    assert "Request is private" in responses[-1].text

    await _dispatch(app, alias, "_admin_alias", f"/admin.alias approve {request.id} 1 已核实", 102, 456)
    hits = await client.catalog.query_alias_exact("maimai", "待审简称")
    assert hits == [(MAI_SONG_ID, "待审简称")]
    assert (await client.catalog.search_song("maimai", "待审简称"))[0].song_id == MAI_SONG_ID
    evidence = await AliasEvidence.filter(request_id=request.id).first()
    await _dispatch(app, alias, "_admin_alias", f"/admin.alias retract {evidence.id} 别名错误", 103, 456)
    retract = await AliasRequest.filter(operation="RETRACT_EVIDENCE").first()
    await _dispatch(app, alias, "_admin_alias", f"/admin.alias approve {retract.id} 1 自己审核", 104, 456)
    assert "SELF_REVIEW" in responses[-1].text
    await _dispatch(app, alias, "_admin_alias", f"/admin.alias approve {retract.id} 1 已核实", 105, 789)
    assert not await client.catalog.query_alias_exact("maimai", "待审简称")
    assert all(r.match_type.value != "exact_alias" for r in await client.catalog.search_song("maimai", "待审简称"))
    await _dispatch(app, alias, "_admin_alias", f"/admin.alias approve {retract.id} 1 重复审核", 106, 789)
    assert "ALREADY_DECIDED_OR_CHANGED" in responses[-1].text


async def test_pending_summaries_show_titles_and_paginate_only_when_more_exist(app, seeded_song_db, monkeypatch):
    from arcade_helper.aliases import AliasService
    from src.plugins.chiffon_bot.app.commands import alias
    client = alias.lxns_client
    monkeypatch.setattr(nonebot.get_driver().config, 'superusers', {'456'})
    first = await _import_song('sdvx', title='conflict')
    second = await _import_song('sdvx', title='FLOWER', native='2')
    actor = (await client.data.users.from_platform('qq', '123')).user_id
    service = AliasService(client.identities, policy=lambda *_: True, daily_limit=50, pending_limit=50)
    requests = []
    for i in range(21):
        requests.append(await service.submit(actor_id=actor, operation='ADD_ALIAS', idempotency_key=f'page-{i}',
            payload={'game_song_id': first if i == 0 else second, 'text': 'testAlias' if i < 2 else f'alias-{i}',
                     'scope': 'game_song', 'origin_game': 'sdvx'}))
    async def no_full_details(*args, **kwargs):
        pytest.fail('pending must not load full request details or collision searches')
    monkeypatch.setattr(client.data.aliases, 'get_request', no_full_details)
    responses = []
    _finish_capture(monkeypatch, alias, responses)
    await _dispatch(app, alias, '_admin_alias', '/admin.alias pending', 401, 456)
    text = responses[-1].text
    assert '[sdvx] conflict → testAlias（仅此游戏）' in text
    assert '[sdvx] FLOWER → testAlias（仅此游戏）' in text
    assert "game_song_id" not in text and '游标' not in text
    assert f'下一页：/admin.alias pending {requests[19]}' in text
    assert f'#{requests[20]} v1' not in text
    await _dispatch(app, alias, '_admin_alias', f'/admin.alias pending {requests[19]}', 402, 456)
    assert f'#{requests[20]} v1' in responses[-1].text and '下一页' not in responses[-1].text
    await _dispatch(app, alias, '_admin_alias', f'/admin.alias pending {requests[20]}', 403, 456)
    assert responses[-1].text == '暂无可见的待审核请求'
    await service.withdraw(requests[-1], actor_id=actor, expected_version=1)
    await _dispatch(app, alias, '_admin_alias', '/admin.alias pending', 404, 456)
    assert '下一页' not in responses[-1].text  # Exactly one full page has no next page.


async def test_alias_numeric_native_ids_do_not_select_internal_id_collisions(app, seeded_song_db, monkeypatch):
    from src.plugins.chiffon_bot.app.commands import alias
    wrong = await _import_song('maimai', title='Other Native Song', native='5000')
    wanted = await _import_song('maimai', title='Wanted Native Song', native=str(wrong))
    async def no_full_catalog_search(*args, **kwargs):
        pytest.fail('alias commands must use the bounded identity/evidence query path')
    monkeypatch.setattr(alias.lxns_client.catalog, 'search_song', no_full_catalog_search)
    responses = []
    _finish_capture(monkeypatch, alias, responses)
    await _dispatch(app, alias, '_alias', f'/arcade.alias add maimai {wrong} nativeAlias', 411, 123)
    assert (await AliasRequest.all().first()).payload['game_song_id'] == wanted
    await _dispatch(app, alias, '_alias', f'/arcade.alias maimai {wrong}', 412, 123)
    assert 'Wanted Native Song' in responses[-1].text and 'Other Native Song' not in responses[-1].text


async def test_natural_language_ambiguous_alias_never_selects_first(app, seeded_song_db, monkeypatch):
    from src.plugins.chiffon_bot.app.commands import natural_language
    first = await _import_song("sdvx", aliases=["same nickname"])
    second = await _import_song("sdvx", title="Different Work", artist="Other", aliases=["same nickname"], native="2")
    responses = []
    _finish_capture(monkeypatch, natural_language, responses)
    async def ack(*_args, **_kwargs):
        pass
    async def sites():
        return [{"gameCode": "sdvx"}]
    monkeypatch.setattr(natural_language, "ack_message", ack)
    monkeypatch.setattr(natural_language.lxns_client.data.catalog.arcade_songs, "sites", sites)
    await _dispatch(app, natural_language, "handle_cross_game_song_query", "same nickname是什么歌？", 201, 123)
    assert f"/arcade.song sdvx {first}" in responses[-1].text
    assert f"/arcade.song sdvx {second}" in responses[-1].text
    assert "请选择" in responses[-1].text


async def test_alias_query_combines_sources_without_merging_evidence(app, seeded_song_db, monkeypatch):
    from arcade_helper.aliases import AliasObservation
    from arcade_helper.catalog import CatalogRecord
    from src.plugins.chiffon_bot.app.commands import alias

    client = alias.lxns_client
    song = await client.catalog.get_song_by_id("maimai", MAI_SONG_ID)
    song = song.model_copy(update={"alias_observations": [
        AliasObservation(source_key="lxns:maimai", text="ＬＩＧＨＴ"),
        AliasObservation(source_key="dxrating:maimai", text="LIGHT"),
        AliasObservation(source_key="yuzuchan:maimai", text="light"),
        AliasObservation(source_key="lxns:maimai", text="LIGHT", scope="game_song"),
    ]})
    await client.identities.import_records("maimai", [CatalogRecord(song, {}, str(MAI_SONG_ID))],
                                           provider="catalog", namespace="native", complete=False)
    internal_id = await client.catalog.internal_song_id("maimai", MAI_SONG_ID)
    before = await client.data.aliases.get_effective_aliases(internal_id)
    responses = []
    _finish_capture(monkeypatch, alias, responses)
    await _dispatch(app, alias, "_alias", f"/arcade.alias maimai {MAI_SONG_ID}", 301, 123)
    lines = responses[-1].text.splitlines()
    assert [line for line in lines if line.lower().startswith("light | work | ")] == [
        "LIGHT | work | 来源 dxrating:maimai、lxns:maimai、yuzuchan:maimai"
    ]
    assert "LIGHT | game_song | 来源 lxns:maimai" in lines
    assert await client.data.aliases.get_effective_aliases(internal_id) == before
    assert len([e for e in before if e["alias_key"] == "light"]) == 4


@pytest.mark.parametrize("choice,ambiguous", [("1", False), ("舞萌", False), ("2", False), ("sdvx", False), ("2", True)])
async def test_natural_language_game_choice_dispatches_reply(app, seeded_song_db, monkeypatch, choice, ambiguous):
    from tests.fixtures.song_seed import MAI_SONG_TITLE
    from src.plugins.chiffon_bot.app.commands import arcade, natural_language
    from src.plugins.chiffon_bot.shared.game import get_domain_adapter

    first = await _import_song("sdvx", title=MAI_SONG_TITLE)
    second = await _import_song("sdvx", title="Another Work", native="2", aliases=[MAI_SONG_TITLE]) if ambiguous else None
    responses = []
    _finish_capture(monkeypatch, natural_language, responses)
    native_queries = []

    async def ack(*_args, **_kwargs):
        pass

    async def sites():
        return [{"gameCode": "sdvx"}]

    async def collections(song_id):
        return []

    async def render(song):
        native_queries.append(song.id)
        return b"native-song-image"

    async def jacket(*_args, **_kwargs):
        return None

    async def reply(prompt):
        responses.append(prompt)
        waiter = _find_matcher(natural_language, "handle_choice")
        # NoneBug's initial snapshot precedes this dynamically registered matcher.
        waiter._default_state["__nonebug_matcher__"] = waiter
        # Other users and conversations cannot select this user's game.
        ctx = app.context
        bot = nonebot.get_bot("10000")
        ctx.receive_event(bot, _group_event(choice, 402).model_copy(update={"user_id": 999}))
        ctx.should_not_pass_rule(waiter)
        ctx.receive_event(bot, _group_event(choice, 403).model_copy(update={"group_id": 999}))
        ctx.should_not_pass_rule(waiter)
        ctx.receive_event(bot, _group_event(choice, 404))
        ctx.should_pass_rule(waiter)
        ctx.should_finished(waiter)
        await ctx.run()

    adapter = get_domain_adapter("maimai")
    monkeypatch.setattr(adapter, "fetch_collections", collections)
    monkeypatch.setattr(adapter, "render_song_image", render)
    monkeypatch.setattr(arcade, "load_song_jacket_bytes", jacket)
    monkeypatch.setattr(natural_language, "ack_message", ack)
    monkeypatch.setattr(natural_language, "send_with", reply)
    monkeypatch.setattr(natural_language.lxns_client.data.catalog.arcade_songs, "sites", sites)
    await _dispatch(app, natural_language, "handle_cross_game_song_query", f"{MAI_SONG_TITLE}是什么歌？", 401, 123)

    assert "回复序号或游戏名" in responses[0].text
    assert "1. [" in responses[0].text and "2. [sdvx]" in responses[0].text
    if choice in {"1", "舞萌"}:
        assert native_queries == [MAI_SONG_ID]
        assert responses[-1].image == b"native-song-image"
    else:
        assert not native_queries
        if ambiguous:
            assert f"/arcade.song sdvx {first}" in responses[-1].text
            assert f"/arcade.song sdvx {second}" in responses[-1].text
            assert "请选择" in responses[-1].text
        else:
            assert f"{MAI_SONG_TITLE} ({first})" in responses[-1].text


async def test_alias_add_resolves_titles_aliases_and_shared_works(app, seeded_song_db, monkeypatch):
    from arcade_helper.storage.tortoise.catalog_models import GameSong
    from src.plugins.chiffon_bot.app.commands import alias

    first = await _import_song("sdvx", title="Transcend Lights", aliases=["超越光"])
    linked = await _import_song("ongeki", title="Transcend Lights")
    responses = []
    _finish_capture(monkeypatch, alias, responses)
    monkeypatch.setattr(nonebot.get_driver().config, "superusers", {"456"})
    commands = [
        f"/arcade.alias add sdvx {first} testAlias",
        '/arcade.alias add sdvx "Transcend Lights" 游戏简称',
        '/arcade.alias add "超越光" 跨游戏简称',
    ]
    for index, command in enumerate(commands):
        await _dispatch(app, alias, "_alias", command, 501 + index * 2, 123)
        request = await AliasRequest.all().order_by("-id").first()
        await _dispatch(app, alias, "_admin_alias", f"/admin.alias approve {request.id} 1 已核实", 502 + index * 2, 456)
    requests = await AliasRequest.all().order_by("id")
    assert [request.payload["scope"] for request in requests] == ["game_song", "game_song", "work"]
    assert [request.payload["origin_game"] for request in requests] == ["sdvx", "sdvx", None]
    assert len({str((await GameSong.get(id=request.payload["game_song_id"])).work_id) for request in requests}) == 1
    sdk = alias.lxns_client.data.aliases
    assert {c.game_song_id for c in (await sdk.resolve_alias("跨游戏简称")).candidates} == {first, linked}
    assert {c.game_song_id for c in (await sdk.resolve_alias("testAlias")).candidates} == {first}
    assert {c.game_song_id for c in (await sdk.resolve_alias("游戏简称")).candidates} == {first}


@pytest.mark.parametrize("specified_game,fuzzy,reply_text", [(True, False, "2"), (False, False, "2"), (True, True, "1"), (False, False, "99")])
async def test_alias_add_selects_target_from_real_reply(app, seeded_song_db, monkeypatch, specified_game, fuzzy, reply_text):
    from src.plugins.chiffon_bot.app.commands import alias, natural_language

    first = await _import_song("sdvx", aliases=["same nickname"])
    await _import_song("ongeki")  # A confirmed second entry must not become a second work option.
    second = await _import_song("sdvx", title="Different Work", artist="Other", aliases=["same nickname"], native="2")
    responses = []
    _finish_capture(monkeypatch, alias, responses)

    async def reply(prompt):
        responses.append(prompt)
        assert not await AliasRequest.all().count()
        waiter = _find_matcher(natural_language, "handle_choice")
        waiter._default_state["__nonebug_matcher__"] = waiter
        ctx = app.context
        ctx.receive_event(nonebot.get_bot("10000"), _group_event(reply_text, 602))
        ctx.should_pass_rule(waiter)
        ctx.should_finished(waiter)
        await ctx.run()

    monkeypatch.setattr(natural_language, "send_with", reply)
    query = "FLOWE" if fuzzy else '"same nickname"'
    game = "sdvx " if specified_game else ""
    await _dispatch(app, alias, "_alias", f"/arcade.alias add {game}{query} 新简称", 601, 123)
    assert "回复序号" in responses[0].text
    assert f"[{first}] FLOWER" in responses[0].text
    if not fuzzy:
        assert "3." not in responses[0].text
        assert f"[{second}] Different Work" in responses[0].text
    if reply_text == "99":
        assert not await AliasRequest.all().count()
        assert "已取消" in responses[-1].text
    else:
        request = await AliasRequest.all().get()
        assert request.payload["game_song_id"] == (first if fuzzy else second)
        assert request.payload["scope"] == ("game_song" if specified_game else "work")
        assert request.payload["origin_game"] == ("sdvx" if specified_game else None)
        assert request.payload["text"] == "新简称"
