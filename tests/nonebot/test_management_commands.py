from types import SimpleNamespace

import pytest


@pytest.mark.parametrize('argument,path,group_id,access', [
    ('', '/manage/', None, 'allow'),
    ('789', '/manage/clanbattle/', 789, 'allow'),
    ('公会战', '/manage/clanbattle/', None, 'allow'),
    ('公会战 789', '/manage/clanbattle/', 789, 'allow'),
    ('别名', '/manage/aliases/', None, 'allow'),
    ('未知模块', None, None, 'allow'),
    ('别名 789 extra', None, None, 'allow'),
    ('公会战 0789', None, None, 'allow'),
    ('别名', None, None, 'disabled'),
    ('公会战 789', None, 789, 'denied'),
])
async def test_group_never_receives_credentials_and_private_link_binds_identity(app, monkeypatch, argument, path, group_id, access):
    import nonebot
    nonebot.require("src.plugins.management")
    from nonebot.adapters.onebot.v11 import Adapter, Bot, PrivateMessageEvent
    from src.plugins import management
    from tests.nonebot.test_arcade_queries import _group_event
    calls, sent = [], []
    async def send(bot, event, message):
        sent.append(message)
    async def open_link(**identity):
        calls.append(identity)
        return "https://manage.example/manage/#temporary"
    monkeypatch.setattr(management, "send_to_event", send)
    monkeypatch.setattr(management, "bridge", SimpleNamespace(open=open_link))
    monkeypatch.setattr(management.config, "management_web_enabled", True)
    monkeypatch.setattr(management.config, "management_web_relay_url", "https://manage.example")
    monkeypatch.setattr(management.config, "management_web_relay_token", "x" * 32)
    monkeypatch.setattr(management, "context_allowed", lambda plugin, *args: not (access == 'disabled' and plugin == 'chiffon_bot'))
    async def authorize(member):
        assert member.platform_id == '123' and member.bot_id == '10000' and member.group_id == group_id
        return access != 'denied'
    monkeypatch.setattr(management.portal, 'modules', {
        'clanbattle':SimpleNamespace(plugin='priconne', authorize=authorize),
        'aliases':SimpleNamespace(plugin='chiffon_bot', authorize=authorize),
    })
    event = _group_event("/管理后台" + (' '+argument if argument else ''), 952)
    async with app.test_matcher(management.command) as ctx:
        bot = ctx.create_bot(base=Bot, adapter=ctx.create_adapter(base=Adapter), self_id="10000")
        ctx.receive_event(bot, event)
    assert not calls and "私聊" in sent[-1]
    data = event.model_dump(); data.pop("group_id")
    data.update(message_type="private", sub_type="friend", message_id=953)
    async with app.test_matcher(management.command) as ctx:
        bot = ctx.create_bot(base=Bot, adapter=ctx.create_adapter(base=Adapter), self_id="10000")
        ctx.receive_event(bot, PrivateMessageEvent(**data))
    if path is None:
        assert not calls and '#temporary' not in sent[-1]
        assert ('格式' if access == 'allow' else '权限') in sent[-1]
    else:
        assert len(calls) == 1 and calls[0]['page_path'] == path
        assert calls[0]["platform_id"] == "123" and calls[0]["bot_id"] == "10000"
        assert calls[0]["group_id"] == group_id and "#temporary" in sent[-1]
    assert not management.portal.sessions.members
