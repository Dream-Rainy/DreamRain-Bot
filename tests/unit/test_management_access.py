import pytest


def test_session_revocation_expiry_and_business_identity_separation(app):
    import nonebot
    nonebot.require("src.plugins.management")
    from src.plugins.management.session import Sessions
    now = [100.0]
    sessions = Sessions(clock=lambda: now[0], superusers=lambda: {"onebot:123"})
    identity = dict(platform_id="123", adapter="onebot", label="成员")
    member = sessions.issue(**identity, ttl=2)
    cleaned = []
    member.cleanup.append(lambda: cleaned.append(True))
    assert not hasattr(member, "user_id") and sessions.admin(member)
    now[0] = 103
    with pytest.raises(Exception) as expired:
        sessions.member(member.key)
    assert expired.value.status_code == 401 and cleaned == [True]
    sessions.clear()
    assert cleaned == [True]


def test_web_permissions_share_group_user_blocks_and_blacklist(app):
    from src.plugins.permission_admin.core import PermissionManager, _PluginEntry
    manager = PermissionManager()
    manager._by_plugin["priconne"] = _PluginEntry(blocked_groups={456}, blocked_users={123})
    assert not manager.is_context_allowed("priconne", 123, 789)
    assert not manager.is_context_allowed("priconne", 124, 456)
    assert manager.is_context_allowed("priconne", 124, 789)
    manager._global_blacklist.add(124)
    assert not manager.is_context_allowed("management", 124)


def test_wire_data_preserves_large_integers_without_coercing_counts(app):
    import nonebot
    nonebot.require("src.plugins.management")
    from src.plugins.priconne.clanbattle.web import wire_data
    result = wire_data({"damage": 2**60, "members": [("uid", 3)]})
    assert result == {"damage": str(2**60), "members": [["uid", 3]]}
