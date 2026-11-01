from types import SimpleNamespace

import nonebot
import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


@pytest_asyncio.fixture
async def console(app, monkeypatch, tmp_path):
    nonebot.require("src.plugins.management")
    from src.plugins import management
    from src.plugins.priconne import clanbattle
    from src.plugins.priconne.clanbattle import web
    from src.plugins.permission_admin.core import get_permission_manager
    management.portal.sessions.clear()
    monkeypatch.setattr(nonebot.get_driver().config, "superusers", {"999"})
    permission = get_permission_manager()
    monkeypatch.setattr(permission, "_global_blacklist", set())
    monkeypatch.setattr(permission, "_by_plugin", {})
    roles = {123: "member", 456: "admin"}
    class Bot:
        self_id = "10000"
        async def get_group_member_info(self, *, group_id, user_id, **kwargs):
            if group_id != 789 or (user_id not in roles and user_id != 10000):
                raise ValueError("not a member")
            return {"user_id": user_id, "role": roles.get(user_id, "member")}
    monkeypatch.setattr(web, "get_bot", lambda bot_id: Bot())
    monkeypatch.setattr(clanbattle, "_push_settings", {})
    monkeypatch.setattr(clanbattle, "clan_path", str(tmp_path))
    api = FastAPI()
    api.include_router(management.portal.router)
    async with AsyncClient(transport=ASGITransport(app=api), base_url="http://console.internal") as client:
        def login(uid, group=789):
            member = management.portal.sessions.issue(platform_id=str(uid), adapter="onebot", label=f"成员{uid}", bot_id="10000", group_id=group)
            client.headers["Authorization"] = "Bearer " + member.key
            return member
        yield SimpleNamespace(client=client, login=login, portal=management.portal, roles=roles,
                              permission=permission, clan=clanbattle, web=web, path=tmp_path)
    management.portal.sessions.clear()


@pytest_asyncio.fixture
async def editors(console, monkeypatch):
    import asyncio, json, time
    from collections import defaultdict
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from src.plugins.priconne.clanbattle import sql
    from src.plugins.priconne.clanbattle.period import BattlePeriod
    from src.plugins.priconne.clanbattle.carryover import game_day_start
    from src.plugins.priconne.orm.models import Record, Apply, Tree, Subscribe
    c = console
    monkeypatch.setattr(sql, '_correction_workers', asyncio.Semaphore(2))
    monkeypatch.setattr(sql, '_group_writes', defaultdict(asyncio.Lock))
    now = int(time.time()); start = game_day_start(now) - 2*86400
    period = BattlePeriod(42, start, start+5*86400-5*3600)
    config = {'clan_battle_id':42, 'member_by_id':{'123':'成员甲','456':'成员乙'},
              'record_coverage':{'event_id':42,'start':start,'through':now,'complete':True}}
    directory = c.path/'789'; directory.mkdir()
    (directory/'clanbattle.json').write_text(json.dumps(config), encoding='utf-8')
    async def schedule(**kwargs): return period
    monkeypatch.setattr(c.clan,'get_period',schedule)
    monkeypatch.setattr(sql,'clan_path',str(c.path))
    engine=create_async_engine('sqlite+aiosqlite:///:memory:');sessions=async_sessionmaker(engine)
    monkeypatch.setattr(sql,'get_session',sessions)
    async with engine.begin() as conn:
        for model in (Record,Apply,Tree,Subscribe):
            await conn.run_sync(lambda db,model=model:model.__table__.create(db))
    async with sessions() as session:
        for log, killed, uid in [(1,True,123),(2,False,123),(3,False,456)]:
            fields={col.name:0 for col in Record.__table__.columns if col.name!='id'}
            fields.update(group_id=789,pcrid=uid,name='成员甲' if uid==123 else '成员乙',lap=39,boss='1' if log==1 else '2',
                          time=game_day_start(now)+log*10,damage=1000000000 if killed else 300000000,flag=0,
                          battle_log_id=100+log,remain_time=90,battle_time=90,
                          settlement={'event_id':42,'killed':killed,'history_id':log,
                                      'history_damage':1000000 if killed else 300000000,
                                      **({'manual_flag':1,'report':{'max_hp':1000000,'totals':{'123':1000000},'observed_at':now}} if killed else {})})
            session.add(Record(**fields))
        session.add(Apply(group_id=789,uid=123,boss=2,time=now-1,text='等待确认'))
        await session.commit()
    c.sql, c.sessions, c.period, c.directory = sql,sessions,period,directory
    try: yield c
    finally: await engine.dispose()


@pytest_asyncio.fixture
async def live_editors(editors, monkeypatch):
    import time
    from src.plugins.priconne.orm.models import Apply, Tree, Subscribe
    c = editors
    now = int(time.time())
    bosses = [dict(order=n, lap_num=39, stage='D', current_hp=hp, max_hp=500000000,
                   available=True, fighter_num=0)
              for n, hp in enumerate([500000000,150000000,50000000,200000000,300000000], 1)]
    snapshot = dict(time=now, clan_battle_id=c.period.id, bosses=bosses, records_synced_at=now,
                    record_sync_ok=True, monitor_qq_id=456)
    monkeypatch.setattr(c.clan, 'run_group', {789:{'snapshot':snapshot}})
    monkeypatch.setattr(c.clan, 'clanbattle_info', {789:SimpleNamespace(loop_check=True)})
    calls = []
    async def member(**kwargs):
        calls.append(kwargs)
        if kwargs['user_id'] == 999:
            raise RuntimeError('nickname unavailable')
        return dict(user_id=kwargs['user_id'], role=c.roles.get(kwargs['user_id'], 'member'), card='成员'+str(kwargs['user_id']))
    monkeypatch.setattr(c.web, 'get_bot', lambda _:SimpleNamespace(self_id='10000', get_group_member_info=member))
    async with c.sessions() as session:
        session.add_all([Apply(group_id=789, uid=123, boss=1, time=now-10, text='本期申请'),
                         Apply(group_id=789, uid=888, boss=1, time=c.period.start-1, text='上期申请'),
                         Tree(group_id=789, uid=777, boss=2, time=now+60, text='未来挂树'),
                         Tree(group_id=789, uid=999, boss=3, time=now-10, text='本期挂树'),
                         Subscribe(group_id=789, uid=999, boss=3, lap=0, text='不限周目预约')])
        await session.commit()
    c.calls, c.now, c.snapshot = calls, now, snapshot
    c.login(456)
    return c


async def test_online_queue_uses_no_battles_and_only_resolves_visible_unique_members(live_editors, monkeypatch):
    from src.plugins.priconne.clanbattle import service
    c = live_editors
    def no_records(*args):
        pytest.fail('登记队列不需要战绩分析')
    monkeypatch.setattr(service, 'RecordDao', no_records)
    response = await c.client.get('/manage/api/clanbattle/queues')
    assert response.status_code == 200, response.text
    rows = response.json()['report']['sections'][0][2]
    assert len(rows) == 4 and 'QQ 999' in str(rows) and '成员123' in str(rows)
    assert '上期申请' not in str(rows) and '未来挂树' not in str(rows)
    assert sorted(call['user_id'] for call in c.calls if not call.get('no_cache')) == [123,999]
    assert len([call for call in c.calls if call.get('no_cache')]) == 2


@pytest.mark.parametrize('view,state', [('daily','ended'), ('carryover','ended'),
                                        ('carryover','unbound'), ('status','no_bosses')])
async def test_reports_without_damage_context_never_read_records(live_editors, monkeypatch, view, state):
    import json
    from src.plugins.priconne.clanbattle import service
    c = live_editors
    def no_records(*args):
        pytest.fail('该分支不需要读取战绩')
    monkeypatch.setattr(service, 'RecordDao', no_records)
    if state == 'ended':
        monkeypatch.setattr(service, 'time', SimpleNamespace(time=lambda:c.period.end))
    elif state == 'unbound':
        config = json.loads((c.directory/'clanbattle.json').read_text(encoding='utf-8'))
        config['clan_battle_id'] -= 1
        (c.directory/'clanbattle.json').write_text(json.dumps(config), encoding='utf-8')
    else:
        c.snapshot.pop('bosses')
    response = await c.client.get('/manage/api/clanbattle/'+view)
    assert response.status_code == 200, response.text
    assert not [call for call in c.calls if not call.get('no_cache')]
    if view == 'daily':
        assert '已结束' in response.json()['report']['note']
    elif view == 'carryover':
        assert response.json()['report']['sections'][0][2] == []


async def test_online_status_keeps_damage_colors_and_skips_queue_nicknames(live_editors):
    from src.plugins.priconne.orm.models import Record
    c = live_editors
    async with c.sessions() as session:
        for boss in range(1,6):
            for i in range(6):
                fields = {col.name:0 for col in Record.__table__.columns if col.name != 'id'}
                fields.update(group_id=789, pcrid=9000+boss*2+i//3, name='样本', lap=39, boss=str(boss),
                              time=c.now-3600-boss*10-i, damage=100000000, flag=0, battle_log_id=90000+boss*10+i,
                              remain_time=90, battle_time=90,
                              settlement={'event_id':c.period.id, 'manual_flag':0, 'killed':False})
                session.add(Record(**fields))
        await session.commit()
    response = await c.client.get('/manage/api/clanbattle/status')
    assert response.status_code == 200, response.text
    rows = next(section[2] for section in response.json()['report']['sections'] if section[0] == '五王进度')
    assert [row[1]['zone'] for row in rows] == ['健康','建议合刀','烂尾','建议合刀','准备合刀']
    assert rows[0][1]['color'] == '#22C55E' and rows[2][1]['color'] == '#EF4444'
    assert [row[4] for row in rows] == [1,1,0,0,0]
    assert [row[5] for row in rows] == [0,0,1,0,0]
    assert not [call for call in c.calls if not call.get('no_cache')]


async def test_people_self_binding_collision_cleanup_and_failed_save(editors, monkeypatch):
    c=editors;c.login(123)
    async def people():return (await c.client.get('/manage/api/clanbattle/people')).json()
    data=await people()
    body={'period_id':42,'expected':data['version'],'qq':'123','uid':'123'}
    assert (await c.client.post('/manage/api/clanbattle/people/link',json=body)).status_code==200
    c.login(456)
    body.update(expected=(await people())['version'],qq='456')
    assert (await c.client.post('/manage/api/clanbattle/people/link',json=body)).status_code==409
    c.login(123);body.update(qq='456',uid=None)
    assert (await c.client.post('/manage/api/clanbattle/people/link',json=body)).status_code==403
    c.login(456);data=await people();body.update(expected=data['version'],qq='123',uid=None)
    old=(c.directory/'member_links.json').read_bytes()
    async def fail(*args):raise OSError('disk full')
    with monkeypatch.context() as patch:
        patch.setattr(c.clan,'write_config',fail)
        assert (await c.client.post('/manage/api/clanbattle/people/link',json=body)).status_code==503
    assert (c.directory/'member_links.json').read_bytes()==old
    assert (await c.client.post('/manage/api/clanbattle/people/link',json=body)).status_code==200


async def test_registration_cleanup_rejects_stale_content_and_wrong_period(editors):
    from src.plugins.priconne.orm.models import Apply
    from sqlalchemy import update, select
    c=editors;c.login(456)
    data=(await c.client.get('/manage/api/clanbattle/people')).json()
    registration=next(e for row in data['items'] for e in row['registrations'])
    body={'period_id':42, 'expected':registration['expected'],'kind':'apply','id':registration['id']}
    async with c.sessions() as session:
        await session.execute(update(Apply).values(text='新留言'));await session.commit()
    assert (await c.client.post('/manage/api/clanbattle/queues/delete',json=body)).status_code==409
    data=(await c.client.get('/manage/api/clanbattle/people')).json()
    body['expected']=next(e for row in data['items'] for e in row['registrations'])['expected']
    body['period_id']=43
    assert (await c.client.post('/manage/api/clanbattle/queues/delete',json=body)).status_code==409
    body['period_id']=42
    assert (await c.client.post('/manage/api/clanbattle/queues/delete',json=body)).status_code==200
    async with c.sessions() as session: assert list((await session.execute(select(Apply))).scalars())==[]


async def test_correction_preview_save_undo_and_collection_cannot_revive_old_override(editors):
    from src.plugins.priconne.orm.models import Record
    from sqlalchemy import select
    c=editors;c.login(123)
    base='/manage/api/clanbattle/records/2/'
    body={'period_id':42,'flag':'comp','source_id':1,'reason':'核对90秒满补来源'}
    assert (await c.client.post(base+'preview',json=body)).status_code==403
    c.login(456)
    before=(await c.client.get('/manage/api/clanbattle/records/2')).json()['record']
    assert before['flag'] is None
    preview=await c.client.post(base+'preview',json=body)
    assert preview.status_code==200,preview.text
    assert preview.json()['after']['records'][1]['carry_source_id']==1
    assert (await c.client.get('/manage/api/clanbattle/records/2')).json()['record']['revision']==0
    save=await c.client.post(base+'save',json={**body,'expected':preview.json()['version']})
    assert save.status_code==200,save.text
    detail=(await c.client.get('/manage/api/clanbattle/records/2')).json()['record']
    assert detail['manual_flag']==.5 and detail['revision']==1 and detail['history'][0]['actor']=='456'
    stale=await c.sql.RecordDao(789,c.period).get_settlement_records(c.period.start,c.period.end)
    undo={**body,'flag':'auto','source_id':None,'reason':'恢复保守推断'}
    preview=(await c.client.post(base+'preview',json=undo)).json()
    assert (await c.client.post(base+'save',json={**undo,'expected':preview['version']})).status_code==200
    await c.sql.RecordDao(789,c.period).save_settlement_facts(stale)
    detail=(await c.client.get('/manage/api/clanbattle/records/2')).json()['record']
    assert detail['flag'] is None and detail['manual_flag'] is None and detail['revision']==2
    assert len(detail['history'])==2 and detail['history'][-1]['after']=={}
    assert detail['damage']==300000000 and detail['raw_flag']==0 and detail['battle_time']==90
    assert (await c.client.post('/manage/api/clanbattle/records/3/save',json={**body,'expected':preview['version']})).status_code==409


async def test_new_collection_invalidates_preview_and_known_conflicts_never_write(editors):
    from sqlalchemy import update, select
    from src.plugins.priconne.orm.models import Record
    c=editors;c.login(456)
    base='/manage/api/clanbattle/records/2/'
    body={'period_id':42,'flag':'comp','source_id':1,'reason':'确认补偿'}
    preview=(await c.client.post(base+'preview',json=body)).json()
    async with c.sessions() as session:
        await session.execute(update(Record).where(Record.id==3).values(damage=300000001));await session.commit()
    assert (await c.client.post(base+'save',json={**body,'expected':preview['version']})).status_code==409
    assert (await c.client.post(base+'preview',json={**body,'source_id':3})).status_code==409
    # The source is a confirmed kill: reclassifying it as an ordinary non-kill is impossible.
    assert (await c.client.post('/manage/api/clanbattle/records/1/preview',json={**body,'flag':'full','source_id':None})).status_code==409
    async with c.sessions() as session:
        record=(await session.execute(select(Record).where(Record.id==2))).scalar_one()
        assert 'correction_history' not in record.settlement


async def test_auth_expiry_logout_scope_and_unknown_dispatch(console):
    c = console
    assert (await c.client.get("/manage/api/me")).status_code == 401
    member = c.login(123)
    assert (await c.client.get("/manage/api/me")).json()["group_id"] == 789
    assert (await c.client.get("/manage/api/not-a-module/status")).status_code == 404
    assert (await c.client.get("/manage/api/clanbattle/settings?group=790")).status_code == 403
    assert (await c.client.post("/manage/api/clanbattle/status", json={})).status_code == 405
    assert (await c.client.post("/manage/api/logout", json={})).status_code == 200
    assert (await c.client.get("/manage/api/me")).status_code == 401
    member = c.login(123)
    member.expires = 0
    assert (await c.client.get("/manage/api/me")).status_code == 401


async def test_group_roles_are_current_and_plugin_blocks_apply(console):
    from src.plugins.permission_admin.core import _PluginEntry
    c = console
    c.login(123)
    response = await c.client.get("/manage/api/clanbattle/settings")
    assert response.status_code == 200 and response.json()["editable"] is False
    body = {"expected": {"broadcast": True, "rankline": False}, "changes": {"broadcast": False}}
    assert (await c.client.post("/manage/api/clanbattle/settings", json=body)).status_code == 403
    c.login(456)
    c.roles[456] = "member"
    assert (await c.client.post("/manage/api/clanbattle/settings", json=body)).status_code == 403
    c.roles.pop(456)
    assert (await c.client.get("/manage/api/clanbattle/settings")).status_code == 403
    c.login(999, None)
    assert (await c.client.get("/manage/api/clanbattle/settings?group=790")).status_code == 403
    c.login(123)
    c.permission._by_plugin["priconne"] = _PluginEntry(blocked_groups={789})
    assert (await c.client.get("/manage/api/clanbattle/settings")).status_code == 403
    c.permission._global_blacklist.add(123)
    assert (await c.client.get("/manage/api/me")).status_code == 403


async def test_settings_conflict_save_failure_and_qq_share_storage(console, monkeypatch):
    c = console
    c.login(456)
    url = "/manage/api/clanbattle/settings"
    original = (await c.client.get(url)).json()["settings"]
    body = {"expected": original, "changes": {"broadcast": False}}
    assert (await c.client.post(url, json=body)).json()["settings"]["broadcast"] is False
    saved = (c.path / "push_settings.json").read_bytes()
    assert c.clan._push_settings["789"]["broadcast"] is False
    assert (await c.client.post(url, json=body)).status_code == 409
    from src.plugins.priconne.clanbattle.service import update_push_settings
    await update_push_settings(789, "10000", {"rankline": True}, actor="QQ456")
    current = (await c.client.get(url)).json()["settings"]
    assert current == {"broadcast": False, "rankline": True}
    async def fail(*args):
        raise OSError("disk unavailable")
    monkeypatch.setattr(c.clan, "save_json", fail)
    saved = (c.path / "push_settings.json").read_bytes()
    assert (await c.client.post(url, json={"expected": current, "changes": {"broadcast": True}})).status_code == 503
    assert (await c.client.get(url)).json()["settings"] == current
    assert (c.path / "push_settings.json").read_bytes() == saved
    assert (await c.client.post(url, json={"expected": current, "changes": {"password": "secret"}})).status_code == 422


async def test_management_alias_uses_real_identity_and_original_approval(console, seeded_song_db, monkeypatch):
    from arcade_helper.storage.tortoise.catalog_models import GameSong
    from tests.fixtures.song_seed import MAI_SONG_TITLE
    c = console
    monkeypatch.setattr(nonebot.get_driver().config, "superusers", {"456", "789"})
    song = await GameSong.get(title=MAI_SONG_TITLE, game_code="maimai")
    c.login(456, None)
    body = {"payload": {"game_song_id": song.id, "text": "统一后台别名", "scope": "work", "origin_game": "maimai"},
            "idempotency_key": "console-alias", "reason": "实际审批验收"}
    response = await c.client.post("/manage/api/aliases/requests", json=body)
    assert response.status_code == 200, response.text
    request_id = response.json()["id"]
    decision = {"version": 1, "approve": True, "reason": "确认"}
    assert (await c.client.post(f"/manage/api/aliases/requests/{request_id}/review", json=decision)).status_code == 403
    c.login(789, None)
    result = await c.client.post(f"/manage/api/aliases/requests/{request_id}/review", json=decision)
    assert result.status_code == 200, result.text
    detail = await c.client.get(f"/manage/api/aliases/requests/{request_id}")
    assert detail.json()["status"] == "approved"


async def test_management_relay_serves_only_static_assets_and_no_bot_api():
    from html.parser import HTMLParser
    from scripts.management_relay import create_app
    app = create_app(token="a" * 32, public_url="http://127.0.0.1")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://127.0.0.1") as c:
        index = await c.get('/manage/')
        for path in ('/manage/clanbattle/', '/manage/aliases/'):
            response = await c.get(path)
            assert response.status_code == 200 and response.content == index.content
            assert response.headers['content-type'].startswith('text/html')
        class Assets(HTMLParser):
            def handle_starttag(self, tag, attrs):
                attrs = dict(attrs)
                if tag in ('link', 'script'):self.urls.append(attrs.get('href', attrs.get('src')))
        assets = Assets();assets.urls = [];assets.feed(index.text)
        for path in assets.urls:
            assert path.startswith('/')
            response = await c.get(path)
            assert response.status_code == 200
            assert ('text/css' if path.endswith('.css') else 'javascript') in response.headers['content-type']
        assert (await c.get('/arcade/aliases/')).status_code == 200
        assert (await c.get("/arcade/aliases/alias-view.html")).headers["content-type"].startswith("text/html")
        for path in ('/manage/api/me', '/manage/unknown/', '/manage/clanbattle/people/', '/manage/clanbattle/app.js'):
            assert (await c.get(path)).status_code == 404
        assert (await c.get("/manage/%2e%2e/%2e%2e/.env")).status_code == 404


async def test_bridge_entry_is_per_session_and_legacy_default_stays_unchanged(console, monkeypatch):
    import asyncio, importlib
    from time import monotonic
    transport = importlib.import_module('src.plugins.management.bridge')
    from src.plugins.management.portal import PATH
    from src.plugins.chiffon_bot.app.web.relay_bridge import EditorBridge as AliasBridge
    created = []
    class Session:
        def __init__(self, url, token, *, handler, on_close):
            self.on_close = on_close;self.id = str(len(created));created.append(self)
        async def start(self, *, page_path=None):
            self.path = page_path or '/arcade/aliases/'
            self.deadline = monotonic()+600
            await asyncio.sleep(0)
            return 'https://relay.example'+self.path
        async def close(self):await self.on_close()
    monkeypatch.setattr(transport, 'EditorSession', Session)
    bridge = transport.EditorBridge(console.portal, 'https://relay.example', 'x'*32,
        api_path=PATH, base='/manage', page_path='/manage/')
    legacy = AliasBridge(console.portal, 'https://relay.example', 'x'*32)
    try:
        async def open_as(uid, path=None):
            return await bridge.open(platform_id=str(uid), adapter='onebot', label='fixture', bot_id='10000',
                group_id=789 if uid==1 else None, page_path=path)
        paths = ('/manage/clanbattle/', '/manage/aliases/', None)
        results = await asyncio.gather(*(open_as(uid, path) for uid, path in enumerate(paths,1)))
        assert results == ['https://relay.example'+path for path in ('/manage/clanbattle/', '/manage/aliases/', '/manage/')]
        assert bridge.page_path == '/manage/'
        assert sorted((m.platform_id, m.group_id or 0) for m in console.portal.sessions.members.values()) == [('1',789),('2',0),('3',0)]
        url = await legacy.open(platform_id='4', adapter='onebot', label='fixture', bot_id='10000')
        assert url == 'https://relay.example/arcade/aliases/'
    finally:
        await bridge.close();await legacy.close()
    assert not console.portal.sessions.members and not bridge.sessions and not legacy.sessions


async def test_group_proof_reused_only_within_request_and_never_after_role_change(console, monkeypatch):
    import asyncio
    from src.plugins.management.portal import request_scope
    c = console
    bot = c.web.get_bot('10000')
    original = bot.get_group_member_info
    calls = []
    async def member(**kwargs):
        calls.append((kwargs['group_id'], kwargs['user_id']))
        await asyncio.sleep(0)
        return await original(**kwargs)
    bot.get_group_member_info = member
    monkeypatch.setattr(c.web, 'get_bot', lambda _: bot)
    first = c.login(123)
    second = c.login(456)
    responses = await asyncio.gather(*(c.client.get('/manage/api/clanbattle/settings',
        headers={'Authorization':'Bearer '+identity.key}) for identity in (first, second)))
    assert [r.json()['editable'] for r in responses] == [False, True]
    assert sorted(calls) == sorted([(789,10000), (789,123), (789,10000), (789,456)])
    assert request_scope.get() is None
    c.roles[456] = 'member'
    body = {'expected':responses[1].json()['settings'], 'changes':{'broadcast':False}}
    calls.clear()
    assert (await c.client.post('/manage/api/clanbattle/settings', json=body)).status_code == 403
    assert calls == [(789,10000), (789,456)]
    calls.clear(); c.login(999)
    assert (await c.client.get('/manage/api/clanbattle/settings')).status_code == 200
    assert calls == [(789,10000)]
    calls.clear(); c.login(123, None)
    assert (await c.client.get('/manage/api/clanbattle/settings?group=790')).status_code == 403
    assert calls == [(790,10000)]


async def test_read_lifetime_stops_at_game_day_activity_start_and_final_midnight(editors, monkeypatch):
    from src.plugins.priconne.clanbattle import service
    c = editors
    for moment, boundary in [(c.period.start-.25, c.period.start),
                             (c.period.start+86400-.25, c.period.start+86400),
                             (c.period.end-.25, c.period.end), (c.period.start+100, c.period.start+110)]:
        monkeypatch.setattr(service, 'time', SimpleNamespace(time=lambda:moment))
        info = service.freshness(c.period)
        assert info['period_id'] == c.period.id and info['as_of'] == moment
        assert info['valid_until'] == boundary
    monkeypatch.setattr(service, 'time', SimpleNamespace(time=lambda:c.period.end+1))
    c.login(123)
    response = await c.client.get('/manage/api/clanbattle/daily')
    assert response.status_code == 200
    assert '已结束' in response.json()['report']['note']
    assert response.json()['freshness']['period_id'] == c.period.id


async def test_web_damage_tiers_read_real_sql_and_exclude_other_groups_periods_and_short_attacks(console, monkeypatch):
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from src.plugins.priconne.clanbattle import sql
    from src.plugins.priconne.clanbattle.period import BattlePeriod
    from src.plugins.priconne.orm.models import Record
    c = console
    period = BattlePeriod(42, 1790197200, 1790611200)
    async def schedule(**kwargs):
        return period
    async def config(path):
        return {"clan_battle_id": 42, "member_by_id": {"123": "成员"}}
    monkeypatch.setattr(c.clan, "get_period", schedule)
    monkeypatch.setattr(c.clan, "load_config", config)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessions = async_sessionmaker(engine)
    monkeypatch.setattr(sql, "get_session", sessions)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(lambda db: Record.__table__.create(db))
        async with sessions() as session:
            for log, (group, moment, seconds, damage) in enumerate([
                (789, period.start + 3600, 90, 50_000_000),
                (789, period.start + 7200, 57, 90_000_000),
                (790, period.start + 3600, 90, 900_000_000),
                (789, period.start - 1, 90, 800_000_000),
                (789, period.end, 90, 700_000_000)], 1):
                fields = {col.name: 0 for col in Record.__table__.columns if col.name != "id"}
                fields.update(group_id=group, pcrid=123, name="成员", lap=39, boss="2", time=moment,
                              damage=damage, battle_log_id=log, remain_time=seconds, battle_time=seconds)
                session.add(Record(**fields))
            await session.commit()
        c.login(123)
        response = await c.client.get("/manage/api/clanbattle/ranges")
        assert response.status_code == 200, response.text
        groups = response.json()["report"]["columns"][1]["groups"]
        assert groups == [{"range": "0.50亿", "count": 1, "members": [["成员", 1]]}]
    finally:
        await engine.dispose()
async def test_undo_can_remove_an_old_override_while_other_conflicts_remain(editors):
    from sqlalchemy import select
    from src.plugins.priconne.orm.models import Record
    c=editors;c.login(456)
    async with c.sessions() as session:
        rows=list((await session.execute(select(Record).where(Record.pcrid==123).order_by(Record.id))).scalars())
        rows[0].settlement={**rows[0].settlement,'manual_flag':0}
        rows[1].settlement={**rows[1].settlement,'manual_flag':.5,'manual_source':1}
        await session.commit()
    body={'period_id':42,'flag':'auto','source_id':None,'reason':'先撤销目标记录的旧覆盖，其他冲突继续核验'}
    preview=await c.client.post('/manage/api/clanbattle/records/2/preview',json=body)
    assert preview.status_code==200 and preview.json()['after']['status']=='conflict'
    saved=await c.client.post('/manage/api/clanbattle/records/2/save',json={**body,'expected':preview.json()['version']})
    assert saved.status_code==200 and saved.json()['after']['status']=='conflict'
    async with c.sessions() as session:
        row=(await session.execute(select(Record).where(Record.id==2))).scalar_one()
        assert 'manual_flag' not in row.settlement and row.settlement['correction_history'][-1]['after']=={}

async def test_freshness_only_updates_do_not_invalidate_an_unchanged_correction_preview(editors):
    import json, time
    from sqlalchemy import select
    from src.plugins.priconne.orm.models import Record
    c=editors;c.login(456)
    path=c.directory/'clanbattle.json'
    config=json.loads(path.read_text(encoding='utf-8'))
    config['record_coverage']['through']=int(time.time())-60
    path.write_text(json.dumps(config),encoding='utf-8')
    body={'period_id':42,'flag':'comp','source_id':1,'reason':'确认满补来源'}
    preview=await c.client.post('/manage/api/clanbattle/records/2/preview',json=body)
    assert preview.status_code==200,preview.text
    config['record_coverage']['through']=int(time.time())
    path.write_text(json.dumps(config),encoding='utf-8')
    async with c.sessions() as session:
        source=(await session.execute(select(Record).where(Record.id==1))).scalar_one()
        meta=dict(source.settlement)
        meta['report']={**meta['report'],'observed_at':int(time.time())+1}
        source.settlement=meta;await session.commit()
    saved=await c.client.post('/manage/api/clanbattle/records/2/save',json={**body,'expected':preview.json()['version']})
    assert saved.status_code==200,saved.text


@pytest.mark.parametrize('change', ['peer', 'insert', 'coverage', 'report_selection', 'heartbeat'])
async def test_correction_rechecks_changes_while_computation_does_not_hold_group_lock(editors, monkeypatch, change):
    import asyncio, json, threading
    from sqlalchemy import select
    from src.plugins.priconne.orm.models import Record
    c = editors; c.login(456)
    if change == 'report_selection':
        async with c.sessions() as session:
            for record_id, maximum, stamp in [(2, 900000000, 20), (3, 1000000000, 10)]:
                row = (await session.execute(select(Record).where(Record.id == record_id))).scalar_one()
                row.settlement = {**row.settlement, 'report':dict(max_hp=maximum,
                    totals={'123':300000000, '456':300000000}, observed_at=stamp)}
            await session.commit()
    path = '/manage/api/clanbattle/records/2/'
    body = dict(period_id=42, flag='comp', source_id=1, reason='核验计算期间的数据变化')
    preview = (await c.client.post(path+'preview', json=body)).json()
    entered, release = threading.Event(), threading.Event()
    prepare = c.sql._prepare_correction
    def pause(*args):
        result = prepare(*args)
        entered.set()
        assert release.wait(10), 'test did not release correction worker'
        return result
    monkeypatch.setattr(c.sql, '_prepare_correction', pause)
    pending = asyncio.create_task(c.client.post(path+'save', json={**body, 'expected':preview['version']}))
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        async def collect():
            async with c.sql.group_write_lock(789):
                if change in ('coverage', 'heartbeat'):
                    file = c.directory/'clanbattle.json'
                    config = json.loads(file.read_text(encoding='utf-8'))
                    if change == 'coverage':config['record_coverage']['complete'] = False
                    else:config['record_coverage']['through'] += 1
                    file.write_text(json.dumps(config), encoding='utf-8')
                async with c.sessions() as session:
                    row = (await session.execute(select(Record).where(Record.id == 3))).scalar_one()
                    if change == 'peer':row.damage += 1
                    elif change == 'insert':
                        values = {col.name:getattr(row, col.name) for col in Record.__table__.columns if col.name != 'id'}
                        values.update(battle_log_id=104, time=row.time+1)
                        session.add(Record(**values))
                    elif change in ('report_selection', 'heartbeat'):
                        if change == 'heartbeat':row = (await session.execute(select(Record).where(Record.id == 1))).scalar_one()
                        row.settlement = {**row.settlement, 'report':{**row.settlement['report'], 'observed_at':30}}
                    await session.commit()
        await asyncio.wait_for(collect(), 5)
    finally:
        release.set()
        response = await pending
    assert response.status_code == (200 if change == 'heartbeat' else 409), response.text
    async with c.sessions() as session:
        row = (await session.execute(select(Record).where(Record.id == 2))).scalar_one()
        assert len(row.settlement.get('correction_history', [])) == (1 if change == 'heartbeat' else 0)


async def test_cancelled_correction_never_saves_or_releases_a_running_worker_slot(editors, monkeypatch):
    import asyncio, threading
    from sqlalchemy import select
    from src.plugins.priconne.orm.models import Record
    c = editors
    dao = c.sql.RecordDao(789, c.period)
    preview = await dao.correct_record(2, .5, source=1, reason='核对来源')
    monkeypatch.setattr(c.sql, '_correction_workers', asyncio.Semaphore(1))
    entered, release, second = threading.Event(), threading.Event(), threading.Event()
    prepare = c.sql._prepare_correction
    def pause(*args):
        result = prepare(*args)
        if not entered.is_set():
            entered.set()
            assert release.wait(10)
        else:second.set()
        return result
    monkeypatch.setattr(c.sql, '_prepare_correction', pause)
    pending = asyncio.create_task(dao.correct_record(2, .5, source=1, reason='核对来源', expected=preview['version'], commit=True))
    follower = None
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        pending.cancel();await asyncio.sleep(0)
        follower = asyncio.create_task(dao.correct_record(2, .5, source=1, reason='核对来源'))
        await asyncio.sleep(0)
        assert not pending.done() and not second.is_set()
        async with c.sql.group_write_lock(789):
            async with c.sessions() as session:
                row = (await session.execute(select(Record).where(Record.id == 2))).scalar_one()
                assert not row.settlement.get('correction_history')
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):await pending
        if follower is not None:assert (await follower)['saved'] is False
    assert second.is_set()
    async with c.sessions() as session:
        row = (await session.execute(select(Record).where(Record.id == 2))).scalar_one()
        assert not row.settlement.get('correction_history')


@pytest.mark.parametrize('boundary', ['game_day', 'end'])
async def test_people_snapshot_keeps_capture_time_and_releases_group_lock(editors, monkeypatch, boundary):
    import asyncio, threading
    from src.plugins.priconne.clanbattle import service
    c = editors;c.login(456)
    cutoff = c.period.start+86400 if boundary == 'game_day' else c.period.end
    clock = SimpleNamespace(now=cutoff-1)
    monkeypatch.setattr(service, 'time', SimpleNamespace(time=lambda:clock.now))
    entered, release = threading.Event(), threading.Event()
    build = service._people_snapshot
    def pause(*args):
        entered.set()
        assert release.wait(10)
        return build(*args)
    monkeypatch.setattr(service, '_people_snapshot', pause)
    pending = asyncio.create_task(c.client.get('/manage/api/clanbattle/people'))
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        async def bind():
            return await service.change_member_link(c.web.get_bot('10000'),789,'123','123',actor='456',admin=True)
        await asyncio.wait_for(bind(), 5)
        clock.now = cutoff+1
    finally:
        release.set()
        response = await pending
    assert response.status_code == 200, response.text
    data = response.json()
    assert data['freshness']['as_of'] == cutoff-1 and data['freshness']['valid_until'] == cutoff
    assert data['freshness']['game_day'] == c.sql.game_day_start(cutoff-1)
    assert next(row for row in data['items'] if row['pcrid']=='123')['qq'] == []
    assert next(row for row in (await c.client.get('/manage/api/clanbattle/people')).json()['items'] if row['pcrid']=='123')['qq'] == ['123']
