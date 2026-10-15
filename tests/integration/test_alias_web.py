"""Exercise private editor dispatch against real persisted alias decisions."""
import nonebot
import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from arcade_helper.storage.tortoise.alias_models import AliasRequest
from arcade_helper.storage.tortoise.catalog_models import GameSong
from tests.fixtures.song_seed import MAI_SONG_TITLE

BASE = "/arcade/aliases"
ORIGIN = "http://127.0.0.1"


@pytest_asyncio.fixture
async def portal(seeded_song_db, monkeypatch):
    from src.plugins.chiffon_bot import alias_portal
    alias_portal.sessions.clear()
    monkeypatch.setattr(nonebot.get_driver().config, "superusers", {"456", "789"})
    app = FastAPI()
    app.include_router(alias_portal.router)
    yield alias_portal, app
    alias_portal.sessions.clear()


def browser(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN)


async def authenticate(portal, browser, platform_id):
    # Link authentication is exercised through the real editor transport/browser check.
    p, _ = portal
    user = await p.client.data.users.from_platform("qq", str(platform_id))
    member = p.sessions.issue(user_id=user.user_id, platform_id=str(platform_id),
                              adapter="onebot", label="tester "+str(platform_id))
    browser.headers["Authorization"] = f"Bearer {member.key}"
    response = await browser.get(BASE+"/api/me")
    assert response.status_code == 200, response.text
    return response.json()


async def submit(browser, song, text="网页别名", **extra):
    return await browser.post(BASE+"/api/requests", json={"payload":{"game_song_id":song.id,"text":text,"scope":"work","origin_game":song.game_code},"reason":"社区惯用名称","idempotency_key":text,**extra})


async def test_private_editor_session_expiry_revocation_and_no_login_routes(portal):
    p, app = portal
    async with browser(app) as owner, browser(app) as stranger:
        assert (await stranger.get(BASE+"/api/search?q=test")).status_code == 401
        assert (await stranger.get(BASE+"/")).status_code == 404
        assert (await stranger.post(BASE+"/api/login/start", json={})).status_code == 404
        await authenticate(portal, owner, 123)
        assert (await stranger.get(BASE+"/api/me", headers={"Authorization": "Bearer forged"})).status_code == 401
        assert (await owner.post(BASE+"/api/logout", json={})).status_code == 200
        assert (await owner.get(BASE+"/api/search?q=test")).status_code == 401
        await authenticate(portal, owner, 123)
        member = next(iter(p.sessions.members.values()))
        member.expires = p.sessions.clock()-1
        assert (await owner.get(BASE+"/api/me")).status_code == 401


async def test_submit_privacy_no_self_review_current_roles_and_effect(portal, monkeypatch):
    _, app = portal
    song = await GameSong.get(title=MAI_SONG_TITLE, game_code="maimai")
    async with browser(app) as author, browser(app) as reviewer, browser(app) as stranger:
        owner = await authenticate(portal, author,456)
        await authenticate(portal,reviewer,789)
        await authenticate(portal,stranger,123)
        forged = await submit(author,song,actor_id=999)
        assert forged.status_code==422
        submitted = await submit(author,song)
        assert submitted.status_code==200,submitted.text
        request_id=submitted.json()["id"]
        assert (await submit(author,song)).json()["id"]==request_id
        row=await AliasRequest.get(id=request_id)
        assert row.actor_id==owner["user_id"] and row.status=="pending"
        assert not (await stranger.get(BASE+"/api/requests?mine=true")).json()["items"]
        assert (await stranger.get(BASE+f"/api/requests/{request_id}")).status_code==403
        assert (await stranger.get(BASE+"/api/imports")).status_code==403
        assert (await stranger.get(BASE+"/api/requests?mine=false")).status_code==403
        decision={"version":1,"approve":True,"reason":"已核对"}
        assert (await author.post(BASE+f"/api/requests/{request_id}/review",json=decision)).status_code==403
        assert not (await author.get(BASE+"/api/search?q=网页别名")).json()["items"]
        monkeypatch.setattr(nonebot.get_driver().config,"superusers",{"456"})
        assert (await reviewer.post(BASE+f"/api/requests/{request_id}/review",json=decision)).status_code==403
        monkeypatch.setattr(nonebot.get_driver().config,"superusers",{"456","789"})
        approved=await reviewer.post(BASE+f"/api/requests/{request_id}/review",json=decision)
        assert approved.status_code==200,approved.text
        hits=(await author.get(BASE+"/api/search?q=网页别名")).json()["items"]
        assert any(h["id"]==song.id for h in hits)
        assert (await reviewer.post(BASE+f"/api/requests/{request_id}/review",json=decision)).status_code==409
        detail=await reviewer.get(BASE+f"/api/songs/{song.id}")
        assert detail.status_code==200,detail.text
        assert any(e["text"]=="网页别名" for e in detail.json()["evidence"])


async def test_co_submitter_and_explicit_changed_target_confirmation(portal):
    _, app=portal
    song=await GameSong.get(title=MAI_SONG_TITLE,game_code="maimai")
    async with browser(app) as author,browser(app) as co,browser(app) as reviewer:
        await authenticate(portal,author,123);await authenticate(portal,co,456);await authenticate(portal,reviewer,789)
        request_id=(await submit(author,song,"版本确认简称")).json()["id"]
        assert (await submit(co,song,"版本确认简称")).json()["id"]==request_id
        body={"version":1,"approve":True,"reason":"已核对"}
        assert (await co.post(BASE+f"/api/requests/{request_id}/review",json=body)).status_code==403
        assert (await co.post(BASE+f"/api/requests/{request_id}/withdraw",json={"version":1})).status_code==403
        song.version+=1;await song.save(update_fields=["version"])
        detail=(await reviewer.get(BASE+f"/api/requests/{request_id}")).json()
        assert detail["stale"] is True
        assert (await reviewer.post(BASE+f"/api/requests/{request_id}/review",json=body)).status_code==409
        body["confirmed_target_versions"]=detail["current_target_versions"]
        result=await reviewer.post(BASE+f"/api/requests/{request_id}/review",json=body)
        assert result.status_code==200,result.text


async def test_source_mapping_uses_selected_observation_and_real_review(portal):
    p,app=portal
    payload={"songs":[{"songId":"legacy","title":"Bind me","artist":"artist"}]}
    await p.client.identities.import_arcade_catalog("gitadora",payload)
    target=await GameSong.get(game_code="gitadora",title="Bind me")
    changed={"songs":[{"songId":"renamed","title":"Bind me renamed","artist":"artist"}]}
    report=await p.client.identities.import_arcade_catalog("gitadora",changed)
    assert report.pending
    async with browser(app) as author,browser(app) as reviewer:
        await authenticate(portal,author,456);await authenticate(portal,reviewer,789)
        imports=(await author.get(BASE+"/api/imports")).json()
        batch=next(r for r in imports if r["game_code"]=="gitadora")
        pending=(await author.get(BASE+f"/api/imports/{batch['id']}")).json()["items"][0]
        from urllib.parse import urlencode
        records=await author.get(BASE+f"/api/imports/{batch['id']}/records?"+urlencode({"key":pending["external_key"]}))
        assert records.status_code==200,records.text
        record=records.json()[0]
        assert record["raw"]["songId"]=="renamed"
        body={"operation":"MAP_SOURCE_RECORD","payload":{"provider":batch["provider"],"namespace":batch["namespace"],"game_code":"gitadora","external_key":record["external_key"],"record_selector":record["record_selector"],"decision":"bind","target_id":target.id},"idempotency_key":"mapping","reason":"同曲改名"}
        native=await GameSong.get(title=MAI_SONG_TITLE,game_code="maimai")
        body["payload"]["target_id"]=native.id
        assert (await author.post(BASE+"/api/requests",json=body)).status_code==422
        body["payload"]["target_id"]=target.id
        submitted=await author.post(BASE+"/api/requests",json=body)
        assert submitted.status_code==200,submitted.text
        approved=await reviewer.post(BASE+f"/api/requests/{submitted.json()['id']}/review",json={"version":1,"approve":True,"reason":"核对来源与音乐相同"})
        assert approved.status_code==200,approved.text
        target=await GameSong.get(id=target.id)
        assert target.title=="Bind me renamed"
        body["idempotency_key"]="mapping-second"
        second=await author.post(BASE+"/api/requests",json=body)
        assert second.status_code==200,second.text
        stale_id=second.json()["id"]
        await p.client.identities.import_arcade_catalog("gitadora",{"songs":[{"songId":"changed-again","title":"Bind me changed again","artist":"artist"}]})
        assert (await author.get(BASE+f"/api/requests/{stale_id}")).status_code==409
        items=(await author.get(BASE+"/api/requests?mine=true")).json()["items"]
        assert next(r for r in items if r["id"]==stale_id)["can_withdraw"]
        assert (await author.post(BASE+f"/api/requests/{stale_id}/withdraw",json={"version":1})).status_code==200


async def test_matching_candidate_requires_current_version_and_merges_real_works(portal):
    p,app=portal
    for game,artist in (("gitadora","Author A"),("popn","Author B")):
        await p.client.identities.import_arcade_catalog(game,{"songs":[{"title":"Matching candidate","artist":artist}]})
    async with browser(app) as admin:
        await authenticate(portal,admin,456)
        computed=await admin.post(BASE+"/api/associate",json={})
        assert computed.status_code==200,computed.text
        rows=(await admin.get(BASE+"/api/candidates")).json()["items"]
        row=next(r for r in rows if all(s["title"]=="Matching candidate" for s in r["songs"]))
        assert not row["stale"]
        left=await GameSong.get(id=row["left_id"])
        right=await GameSong.get(id=row["right_id"])
        assert left.work_id!=right.work_id
        left.version+=1;await left.save(update_fields=["version"])
        rows=(await admin.get(BASE+"/api/candidates")).json()["items"]
        assert next(r for r in rows if r["id"]==row["id"])["stale"]
        body={"approve":True,"version":row["version"],"reason":"核对原曲录音为同一音乐"}
        assert (await admin.post(BASE+f"/api/candidates/{row['id']}/decide",json=body)).status_code==409
        assert (await admin.post(BASE+"/api/associate",json={})).status_code==200
        fresh=next(r for r in (await admin.get(BASE+"/api/candidates")).json()["items"] if r["id"]==row["id"])
        assert fresh["version"]>row["version"] and not fresh["stale"]
        body["version"]=fresh["version"]
        result=await admin.post(BASE+f"/api/candidates/{row['id']}/decide",json=body)
        assert result.status_code==200,result.text
        left=await GameSong.get(id=left.id);right=await GameSong.get(id=right.id)
        assert left.work_id==right.work_id
        events=(await admin.get(BASE+"/api/events")).json()["items"]
        assert any(e["action"]=="decide_candidate" and e["after"]["id"]==row["id"] for e in events)


async def test_editor_private_command_uses_real_actor_and_refuses_group_links(app,portal,monkeypatch):
    from types import SimpleNamespace
    from nonebot.adapters.onebot.v11 import Adapter,Bot,PrivateMessageEvent
    from src.plugins.chiffon_bot.app import web
    from src.plugins.platform_adapter import PlatformContext
    from tests.nonebot.test_arcade_queries import _group_event,_find_matcher,_finish_capture
    p,_=portal
    calls=[];responses=[]
    async def open_editor(**identity):
        calls.append(("open",identity))
        return "https://editor.example/arcade/aliases/#temporary"
    monkeypatch.setattr(p,"relay",SimpleNamespace(open=open_editor))
    _finish_capture(monkeypatch,web,responses)
    matcher=_find_matcher(web,"_arcade_editor")
    async def dispatch(text,private):
        event=_group_event(text,800+len(responses))
        if private:
            data=event.model_dump();data.pop("group_id")
            data.update(message_type="private",sub_type="friend")
            event=PrivateMessageEvent(**data)
        async with app.test_matcher(matcher) as ctx:
            bot=ctx.create_bot(base=Bot,adapter=ctx.create_adapter(base=Adapter),self_id="10000")
            ctx.receive_event(bot,event)
        return bot,event
    await dispatch("/arcade.editor",False)
    assert not calls and "请私聊" in responses[-1].text
    bot,event=await dispatch("/arcade.editor",True)
    platform=PlatformContext.from_event(event,bot).platform
    actor=await p.client.data.users.from_platform("qq" if "onebot" in platform else platform,"123")
    assert calls[0][1]["user_id"]==actor.user_id
    assert calls[0][1]["platform_id"]=="123"
    assert "#temporary" in responses[-1].text
    assert "打开即可使用" in responses[-1].text
    await dispatch("/arcade.editor unexpected",True)
    assert len(calls)==1 and "无需其他参数" in responses[-1].text
    monkeypatch.setattr(p, "relay", None)
    await dispatch("/arcade.editor", True)
    assert "alias_web_relay_url" in responses[-1].text


@pytest.mark.parametrize("relay_url", ["", "http://127.0.0.1:8765"])
async def test_editor_registration_never_exposes_alias_http_routes(portal, relay_url):
    from types import SimpleNamespace
    from src.plugins.chiffon_bot.app import web
    from src.plugins.chiffon_bot.config import Config
    server = nonebot.get_app()
    before = list(server.routes)
    commands = []
    class Group:
        def command(self, name):
            commands.append(name)
            return SimpleNamespace(handle=lambda: lambda fn: fn)
    p = web.register_alias_web(Group(), Config(alias_web_relay_url=relay_url, alias_web_relay_token="t"*32))
    try:
        assert (p.relay is not None) == bool(relay_url)
        assert commands == ["editor"]
        assert server.routes == before
    finally:
        await p.close()
