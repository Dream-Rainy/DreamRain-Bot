from __future__ import annotations

import json
from types import SimpleNamespace

import pytest


@pytest.fixture()
def clanbattle(app):
    from src.plugins.priconne import clanbattle as module

    return module


def _snapshot():
    return {
        "time": 1_777_777_777,
        "rank": 42,
        "boss": "当前进度：D面3阶段\n30周目1王: HP: 1/2 50%",
    }


def test_monitor_registration_preserves_snapshot(clanbattle, monkeypatch):
    snapshot = _snapshot()
    monkeypatch.setattr(
        clanbattle,
        "run_group",
        {10001: {"self_id": 1, "qq_id": 2, "snapshot": snapshot}},
    )

    clanbattle._set_monitor_registered(10001, self_id=3, qq_id=4)

    assert clanbattle.run_group[10001] == {
        "self_id": 3,
        "qq_id": 4,
        "snapshot": snapshot,
    }


def test_monitor_stop_removes_runtime_fields_but_keeps_snapshot(clanbattle, monkeypatch):
    snapshot = _snapshot()
    monkeypatch.setattr(
        clanbattle,
        "run_group",
        {10001: {"self_id": 1, "qq_id": 2, "snapshot": snapshot}},
    )

    clanbattle._set_monitor_stopped(10001)

    assert clanbattle.run_group == {10001: {"snapshot": snapshot}}


def test_monitor_stop_removes_entry_without_snapshot(clanbattle, monkeypatch):
    monkeypatch.setattr(
        clanbattle,
        "run_group",
        {10001: {"self_id": 1, "qq_id": 2}},
    )

    clanbattle._set_monitor_stopped(10001)

    assert clanbattle.run_group == {}


def test_set_snapshot_preserves_monitor_registration(clanbattle, monkeypatch):
    snapshot = _snapshot()
    monkeypatch.setattr(
        clanbattle,
        "run_group",
        {10001: {"self_id": 1, "qq_id": 2}},
    )

    saved = clanbattle._set_monitor_snapshot(10001, snapshot)

    assert saved is True
    assert clanbattle.run_group[10001]["snapshot"] == snapshot
    assert clanbattle.run_group[10001]["self_id"] == 1
    assert clanbattle.run_group[10001]["qq_id"] == 2


def test_restore_keeps_active_and_snapshot_only_groups(clanbattle, monkeypatch):
    snapshot = _snapshot()
    monkeypatch.setattr(clanbattle, "run_group", {99999: {"qq_id": 9}})

    clanbattle._restore_run_group(
        {
            "10001": {"self_id": 1, "qq_id": 2, "snapshot": snapshot},
            "10002": {"snapshot": snapshot},
        }
    )

    assert set(clanbattle.run_group) == {10001, 10002}
    assert clanbattle.run_group[10001]["snapshot"] == snapshot
    assert clanbattle.run_group[10002] == {"snapshot": snapshot}


async def test_cancel_monitor_persists_snapshot_only_entry(clanbattle, monkeypatch):
    snapshot = _snapshot()
    clan_info = SimpleNamespace(qq_id=20001, loop_num=7, loop_check=1_777_777_777)
    monkeypatch.setattr(clanbattle, "clanbattle_info", {10001: clan_info})
    monkeypatch.setattr(
        clanbattle,
        "run_group",
        {10001: {"self_id": 1, "qq_id": 20001, "snapshot": snapshot}},
    )
    persisted = []

    async def fake_save_run_group():
        persisted.append(clanbattle.run_group.copy())

    monkeypatch.setattr(clanbattle, "_save_run_group", fake_save_run_group)
    bot = SimpleNamespace(send=None)
    event = SimpleNamespace(group_id=10001, user_id=20001)

    await clanbattle.delete_monitor(bot, event)

    assert clan_info.loop_num == 8
    assert clan_info.loop_check is False
    assert clanbattle.run_group == {10001: {"snapshot": snapshot}}
    assert persisted == [{10001: {"snapshot": snapshot}}]


async def test_status_is_offline_immediately_after_cancel(clanbattle, monkeypatch):
    snapshot = _snapshot()
    clan_info = SimpleNamespace(qq_id=20001, loop_num=7, loop_check=1_777_777_777)
    monkeypatch.setattr(clanbattle, "clanbattle_info", {10001: clan_info})
    monkeypatch.setattr(
        clanbattle,
        "run_group",
        {10001: {"self_id": 1, "qq_id": 20001, "snapshot": snapshot}},
    )

    async def fake_save_run_group():
        return None

    async def fake_load_config(path):
        return {"10001": clanbattle.run_group[10001]}

    sent = []

    async def fake_safe_send(bot, event, message):
        sent.append(message)

    async def unexpected_send(event, message):
        raise AssertionError(message)

    monkeypatch.setattr(clanbattle, "_save_run_group", fake_save_run_group)
    monkeypatch.setattr(clanbattle, "load_config", fake_load_config)
    monkeypatch.setattr(clanbattle, "safe_send", fake_safe_send)
    bot = SimpleNamespace(send=unexpected_send)
    event = SimpleNamespace(group_id=10001, user_id=20001)

    await clanbattle.delete_monitor(bot, event)
    await clanbattle.daostate(bot, event)

    assert len(sent) == 1
    assert "监控状态：关闭" in sent[0]
    assert "历史排名：42" in sent[0]


async def test_unauthorized_cancel_keeps_monitor_running(clanbattle, monkeypatch):
    snapshot = _snapshot()
    clan_info = SimpleNamespace(qq_id=20001, loop_num=7, loop_check=1_777_777_777)
    original_entry = {"self_id": 1, "qq_id": 20001, "snapshot": snapshot}
    monkeypatch.setattr(clanbattle, "clanbattle_info", {10001: clan_info})
    monkeypatch.setattr(clanbattle, "run_group", {10001: original_entry.copy()})
    monkeypatch.setattr(clanbattle.priv, "check_priv", lambda event, level: False)
    sent = []

    async def send(event, message):
        sent.append(message)

    bot = SimpleNamespace(send=send)
    event = SimpleNamespace(group_id=10001, user_id=20002)

    await clanbattle.delete_monitor(bot, event)

    assert sent == ["你不是监控人或者管理"]
    assert clan_info.loop_num == 7
    assert clan_info.loop_check == 1_777_777_777
    assert clanbattle.run_group == {10001: original_entry}


async def test_offline_status_uses_persisted_snapshot(clanbattle, monkeypatch):
    snapshot = _snapshot()
    monkeypatch.setattr(clanbattle, "clanbattle_info", {})

    async def fake_load_config(path):
        return {"10001": {"snapshot": snapshot}}

    sent = []

    async def fake_safe_send(bot, event, message):
        sent.append(message)

    async def unexpected_send(event, message):
        raise AssertionError(message)

    monkeypatch.setattr(clanbattle, "load_config", fake_load_config)
    monkeypatch.setattr(clanbattle, "safe_send", fake_safe_send)
    bot = SimpleNamespace(send=unexpected_send)
    event = SimpleNamespace(group_id=10001)

    await clanbattle.daostate(bot, event)

    assert len(sent) == 1
    assert "监控状态：关闭" in sent[0]
    assert "历史排名：42" in sent[0]
    assert snapshot["boss"] in sent[0]


async def test_offline_status_without_snapshot_keeps_existing_prompt(clanbattle, monkeypatch):
    monkeypatch.setattr(clanbattle, "clanbattle_info", {})

    async def fake_load_config(path):
        return {}

    sent = []

    async def send(event, message):
        sent.append(message)

    monkeypatch.setattr(clanbattle, "load_config", fake_load_config)
    bot = SimpleNamespace(send=send)
    event = SimpleNamespace(group_id=10001)

    await clanbattle.daostate(bot, event)

    assert sent == ["未查询到本群历史状态，请开启出刀监控"]


async def test_offline_reminder_requires_superuser(clanbattle, monkeypatch):
    snapshot = _snapshot()
    original = {10001: {"self_id": 1, "qq_id": 2, "snapshot": snapshot}}
    monkeypatch.setattr(clanbattle, "run_group", original.copy())

    async def deny_superuser(bot, event):
        return False

    async def unexpected_save():
        raise AssertionError("unauthorized reminder must not save state")

    sent = []

    async def send(event, message):
        sent.append(message)

    monkeypatch.setattr(clanbattle, "_is_superuser", deny_superuser)
    monkeypatch.setattr(clanbattle, "_save_run_group", unexpected_save)
    bot = SimpleNamespace(send=send)
    event = SimpleNamespace(user_id=20001)

    await clanbattle.notify_offline_monitors(bot, event)

    assert sent == ["权限不足"]
    assert clanbattle.run_group == original


async def test_offline_reminder_only_handles_unrestored_monitors(clanbattle, monkeypatch):
    snapshot = _snapshot()
    now = 1_777_777_777
    monkeypatch.setattr(
        clanbattle,
        "run_group",
        {
            10001: {"snapshot": snapshot},
            10002: {"self_id": 1, "qq_id": 2, "snapshot": snapshot},
            10003: {"self_id": 1, "qq_id": 3, "snapshot": snapshot},
            10004: {"self_id": 1, "qq_id": 4, "snapshot": snapshot},
        },
    )
    monkeypatch.setattr(
        clanbattle,
        "clanbattle_info",
        {
            10002: SimpleNamespace(loop_check=now),
            10003: SimpleNamespace(loop_check=False, loop_num=7),
            10004: SimpleNamespace(loop_check=now - 121),
        },
    )

    async def allow_superuser(bot, event):
        return True

    notified = []

    class FakeCurrentBot:
        async def send_group_msg(self, **kwargs):
            notified.append(kwargs)

    saved = []

    async def fake_save_run_group():
        saved.append({gid: info.copy() for gid, info in clanbattle.run_group.items()})
        return True

    replies = []

    async def send(event, message):
        replies.append(message)

    monkeypatch.setattr(clanbattle, "_is_superuser", allow_superuser)
    monkeypatch.setattr(clanbattle, "get_bot", lambda: FakeCurrentBot())
    monkeypatch.setattr(clanbattle, "_save_run_group", fake_save_run_group)

    await clanbattle.notify_offline_monitors(
        SimpleNamespace(send=send), SimpleNamespace()
    )

    assert [item["group_id"] for item in notified] == [10003]
    assert clanbattle.run_group[10001] == {"snapshot": snapshot}
    assert clanbattle.run_group[10002]["qq_id"] == 2
    assert clanbattle.run_group[10003] == {"snapshot": snapshot}
    assert clanbattle.run_group[10004]["qq_id"] == 4
    assert clanbattle.clanbattle_info[10003].loop_num == 8
    assert saved == [clanbattle.run_group]
    assert replies == ["处理完成"]


async def test_offline_reminder_continues_after_send_failure(clanbattle, monkeypatch):
    snapshot = _snapshot()
    monkeypatch.setattr(
        clanbattle,
        "run_group",
        {
            10001: {"self_id": 1, "qq_id": 2, "snapshot": snapshot},
            10002: {"self_id": 1, "qq_id": 3, "snapshot": snapshot},
        },
    )
    monkeypatch.setattr(clanbattle, "clanbattle_info", {})

    async def allow_superuser(bot, event):
        return True

    notified = []

    class FakeCurrentBot:
        async def send_group_msg(self, **kwargs):
            if kwargs["group_id"] == 10001:
                raise RuntimeError("send failed")
            notified.append(kwargs["group_id"])

    save_count = 0

    async def fake_save_run_group():
        nonlocal save_count
        save_count += 1
        return True

    replies = []

    async def send(event, message):
        replies.append(message)

    monkeypatch.setattr(clanbattle, "_is_superuser", allow_superuser)
    monkeypatch.setattr(clanbattle, "get_bot", lambda: FakeCurrentBot())
    monkeypatch.setattr(clanbattle, "_save_run_group", fake_save_run_group)

    await clanbattle.notify_offline_monitors(
        SimpleNamespace(send=send), SimpleNamespace()
    )

    assert notified == [10002]
    assert clanbattle.run_group == {
        10001: {"snapshot": snapshot},
        10002: {"snapshot": snapshot},
    }
    assert save_count == 1
    assert replies == ["处理完成"]


async def test_cache_run_groups_requires_superuser(clanbattle, monkeypatch):
    async def deny_superuser(bot, event):
        return False

    async def unexpected_save():
        raise AssertionError("unauthorized cache command must not save state")

    replies = []

    async def send(event, message):
        replies.append(message)

    monkeypatch.setattr(clanbattle, "_is_superuser", deny_superuser)
    monkeypatch.setattr(clanbattle, "_save_run_group", unexpected_save)

    await clanbattle.cache_run_groups(SimpleNamespace(send=send), SimpleNamespace())

    assert replies == ["权限不足"]


async def test_cache_run_groups_reports_save_failure(clanbattle, monkeypatch):
    async def allow_superuser(bot, event):
        return True

    async def failed_save():
        return False

    replies = []

    async def send(event, message):
        replies.append(message)

    monkeypatch.setattr(clanbattle, "_is_superuser", allow_superuser)
    monkeypatch.setattr(clanbattle, "_save_run_group", failed_save)

    await clanbattle.cache_run_groups(SimpleNamespace(send=send), SimpleNamespace())

    assert replies == ["保存失败，请检查日志"]


async def test_save_run_group_replaces_file_atomically(clanbattle, monkeypatch, tmp_path):
    run_path = tmp_path / "rungroup.json"
    run_path.write_text('{"old": true}', encoding="utf-8")
    monkeypatch.setattr(clanbattle, "run_path", str(run_path))
    monkeypatch.setattr(clanbattle, "run_group", {10001: {"qq_id": 2}})

    assert await clanbattle._save_run_group() is True
    assert json.loads(run_path.read_text(encoding="utf-8")) == {
        "10001": {"qq_id": 2}
    }
    assert not (tmp_path / "rungroup.json.tmp").exists()


async def test_save_run_group_keeps_original_when_replace_fails(
    clanbattle, monkeypatch, tmp_path
):
    run_path = tmp_path / "rungroup.json"
    original = '{"old": true}'
    run_path.write_text(original, encoding="utf-8")
    monkeypatch.setattr(clanbattle, "run_path", str(run_path))
    monkeypatch.setattr(clanbattle, "run_group", {10001: {"qq_id": 2}})
    monkeypatch.setattr(
        clanbattle.os,
        "replace",
        lambda source, destination: (_ for _ in ()).throw(OSError("replace failed")),
    )

    assert await clanbattle._save_run_group() is False
    assert run_path.read_text(encoding="utf-8") == original


def test_restore_skips_invalid_entries_without_blocking_valid_ones(
    clanbattle, monkeypatch
):
    monkeypatch.setattr(clanbattle, "run_group", {})

    clanbattle._restore_run_group(
        {
            "invalid-group": {"qq_id": 1},
            "10001": "legacy-scalar",
            "10002": {"qq_id": "not-an-id"},
            "10003": {"snapshot": "not-an-object"},
            "10005": {"snapshot": {"time": 1, "rank": 2}},
            "10004": {"qq_id": "2", "snapshot": _snapshot()},
        }
    )

    assert clanbattle.run_group == {
        10004: {"qq_id": 2, "snapshot": _snapshot()}
    }


def _failing_clan(*, error_count=0):
    class FailingClan:
        loop_num = 7
        loop_check = 1_777_777_777
        qq_id = 2

        def __init__(self):
            self.error_count = error_count

        async def get_clanbattle_top(self):
            raise RuntimeError("poll failed")

        async def probe_session(self):
            return False, None, ""

    return FailingClan()


async def test_cancel_during_network_backoff_cannot_restore_registration(
    clanbattle, monkeypatch
):
    snapshot = _snapshot()
    clan_info = _failing_clan()
    monkeypatch.setattr(clanbattle, "clanbattle_info", {10001: clan_info})
    monkeypatch.setattr(
        clanbattle,
        "run_group",
        {10001: {"self_id": 1, "qq_id": 2, "snapshot": snapshot}},
    )
    monkeypatch.setattr(clanbattle, "_is_network_error", lambda error: True)
    states_before_cancel = []

    async def fake_save_run_group():
        return True

    async def fake_loop_send(bot, event, group_id, message):
        return None

    async def cancel_during_sleep(delay):
        states_before_cancel.append(clanbattle.run_group[10001].copy())
        clanbattle._invalidate_monitor_loop(10001)
        clanbattle._set_monitor_stopped(10001)

    monkeypatch.setattr(clanbattle, "_save_run_group", fake_save_run_group)
    monkeypatch.setattr(clanbattle, "_loop_send", fake_loop_send)
    monkeypatch.setattr(clanbattle.asyncio, "sleep", cancel_during_sleep)

    await clanbattle._monitor_loop(None, None, 10001, 2, "account.json", 1, 7)

    assert states_before_cancel == [
        {"self_id": 1, "qq_id": 2, "snapshot": snapshot}
    ]
    assert clan_info.loop_check is False
    assert clanbattle.run_group == {10001: {"snapshot": snapshot}}


async def test_cancel_during_reconnect_cannot_restore_registration(
    clanbattle, monkeypatch
):
    snapshot = _snapshot()
    clan_info = _failing_clan(error_count=2)

    async def reachable_session():
        return True, None, ""

    clan_info.probe_session = reachable_session
    monkeypatch.setattr(clanbattle, "clanbattle_info", {10001: clan_info})
    monkeypatch.setattr(
        clanbattle,
        "run_group",
        {10001: {"self_id": 1, "qq_id": 2, "snapshot": snapshot}},
    )

    async def fake_save_run_group():
        return True

    async def fake_loop_send(bot, event, group_id, message):
        return None

    async def cancel_during_reconnect(group_id, qq_id, account_file):
        clanbattle._invalidate_monitor_loop(group_id)
        clanbattle._set_monitor_stopped(group_id)
        return True

    monkeypatch.setattr(clanbattle, "_save_run_group", fake_save_run_group)
    monkeypatch.setattr(clanbattle, "_loop_send", fake_loop_send)
    monkeypatch.setattr(clanbattle, "_reconnect_once", cancel_during_reconnect)

    await clanbattle._monitor_loop(None, None, 10001, 2, "account.json", 1, 7)

    assert clan_info.loop_check is False
    assert clanbattle.run_group == {10001: {"snapshot": snapshot}}


@pytest.mark.parametrize(
    ("probe_result", "error_count"),
    [
        ((False, 3, "session expired"), 0),
        ((True, None, ""), 10),
    ],
)
async def test_terminal_monitor_failures_remove_registration(
    clanbattle, monkeypatch, probe_result, error_count
):
    snapshot = _snapshot()
    clan_info = _failing_clan(error_count=error_count)

    async def probe_session():
        return probe_result

    clan_info.probe_session = probe_session
    monkeypatch.setattr(clanbattle, "clanbattle_info", {10001: clan_info})
    monkeypatch.setattr(
        clanbattle,
        "run_group",
        {10001: {"self_id": 1, "qq_id": 2, "snapshot": snapshot}},
    )

    async def fake_save_run_group():
        return True

    async def fake_loop_send(bot, event, group_id, message):
        return None

    monkeypatch.setattr(clanbattle, "_save_run_group", fake_save_run_group)
    monkeypatch.setattr(clanbattle, "_loop_send", fake_loop_send)

    await clanbattle._monitor_loop(None, None, 10001, 2, "account.json", 1, 7)

    assert clan_info.loop_check is False
    assert clanbattle.run_group == {10001: {"snapshot": snapshot}}


async def test_registered_retry_state_is_auto_resumed_after_restart(
    clanbattle, monkeypatch
):
    snapshot = _snapshot()
    persisted = {
        "10001": {"self_id": 1, "qq_id": 2, "snapshot": snapshot}
    }
    query_calls = []

    async def fake_load_config(path):
        if path == clanbattle.run_path:
            return persisted
        return [{"account": "stored"}]

    async def fake_query(accounts, captcha_context=None):
        query_calls.append(accounts)
        return SimpleNamespace()

    async def fake_check_client(client):
        return True

    async def fake_store_user_name(account_file, accounts, user_name):
        return None

    async def fake_save_run_group():
        return True

    async def fake_loop_send(bot, event, group_id, message):
        return None

    class FakeClanBattle:
        def __init__(self, group_id):
            self.group_id = group_id
            self.loop_num = 0
            self.loop_check = False
            self.user_name = ""

        async def init(self, client, qq_id):
            self.loop_num += 1
            self.qq_id = qq_id

    launched = []

    def fake_create_task(coroutine):
        launched.append(True)
        coroutine.close()

    monkeypatch.setattr(clanbattle, "_resumed", False)
    monkeypatch.setattr(clanbattle, "run_group", {})
    monkeypatch.setattr(clanbattle, "clanbattle_info", {})
    monkeypatch.setattr(clanbattle, "load_config", fake_load_config)
    monkeypatch.setattr(clanbattle, "query", fake_query)
    monkeypatch.setattr(clanbattle, "check_client", fake_check_client)
    monkeypatch.setattr(clanbattle, "_store_user_name", fake_store_user_name)
    monkeypatch.setattr(clanbattle, "_save_run_group", fake_save_run_group)
    monkeypatch.setattr(clanbattle, "_loop_send", fake_loop_send)
    monkeypatch.setattr(clanbattle, "ClanBattle", FakeClanBattle)
    monkeypatch.setattr(clanbattle.asyncio, "create_task", fake_create_task)

    await clanbattle.resume_monitors(SimpleNamespace())

    assert len(query_calls) == 1
    assert launched == [True]
    assert clanbattle.run_group[10001] == {
        "self_id": 1,
        "qq_id": 2,
        "snapshot": snapshot,
    }
