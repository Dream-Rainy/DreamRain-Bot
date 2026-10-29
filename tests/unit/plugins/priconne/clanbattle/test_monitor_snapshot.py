from __future__ import annotations

import json
import asyncio
from types import SimpleNamespace
from copy import deepcopy

import pytest


async def test_settlement_enrichment_matches_members_and_retries_optional_report_failure(clanbattle):
    from src.plugins.priconne.clanbattle.model import ClanBattle
    from src.plugins.priconne.clanbattle.period import BattlePeriod

    clan = ClanBattle(10001)
    clan.event, clan.clan_battle_id, clan.clan_id, clan.loop_num = BattlePeriod(42, 1000, 2000), 42, 8, 1
    rows = [dict(id=uid, pcrid=uid, name="同名", time=1001, lap=42, boss=str(uid),
                 damage=raw, flag=0, battle_log_id=uid, remain_time=90, battle_time=90, settlement=None)
            for uid, raw in [(1, 500), (2, 700), (3, 900)]]
    for row, actual in zip(rows[:2], (100, 200)):
        row["settlement"] = {"report": dict(max_hp=actual, totals={str(row["pcrid"]): actual},
                                          covered_logs=[[str(row["pcrid"]), row["battle_log_id"]]])}
    calls = []

    async def records(start, end):
        return deepcopy(rows)

    async def save(changed):
        for item in changed:
            rows[item["id"] - 1]["settlement"] = item["settlement"]

    async def api(path, params, **kwargs):
        calls.append((path, params))
        if len(calls) == 1:
            raise RuntimeError("temporary optional metadata failure")
        return {"max_hp": 1000, "damage_report": [{"viewer_id": 3, "damage": 900}]}

    clan.record = SimpleNamespace(get_settlement_records=records, save_settlement_facts=save)
    clan.client = SimpleNamespace(callapi=api)
    history = [dict(viewer_id=uid, lap_num=42, order_num=uid, create_time=1001,
                    history_id=uid, damage=actual, kill=1) for uid, actual in [(1, 100), (2, 200)]]
    await clan._enrich_records(history, [], 1)
    result = list(clan.settlements.values())
    assert [item["effective_damage"] for item in result] == [100, 200, None]
    await clan._enrich_records([], [], 1)
    result = list(clan.settlements.values())
    assert [item["effective_damage"] for item in result] == [100, 200, 900]
    assert [item["damage"] for item in result] == [500, 700, 900]
    await clan._enrich_records([], [], 1)
    assert len(calls) == 2 and calls[-1][1]["order_num"] == 3


async def test_final_sync_keeps_last_second_same_time_records_and_serializes_overlapping_collection(clanbattle):
    from src.plugins.priconne.clanbattle.model import ClanBattle
    from src.plugins.priconne.clanbattle.period import BattlePeriod

    clan = ClanBattle(10001)
    clan.event = BattlePeriod(42, 1000, 2000)
    clan.clan_battle_id = 42
    clan.loop_num = 1
    committed = []

    async def latest():
        return 1999

    async def existing(start, end):
        return [{"pcrid": 123, "battle_log_id": 1},
                *[{"pcrid": row[0], "battle_log_id": row[7]} for row in committed]]

    async def commit(rows):
        await asyncio.sleep(0)
        committed.extend(rows)

    clan.record = SimpleNamespace(get_latest_time=latest, get_report_records=existing, add_record=commit)
    battles = [dict(battle_end_time=moment, battle_type=1, target_viewer_id=123,
                    user_name="成员", order_num=1, lap_num=30, total_damage=100,
                    battle_log_id=log, units=[]) for moment, log in ((1999, 1), (1999, 2), (2000, 3))]

    async def logs(page):
        return {"max_page": 1, "battle_list": battles}

    async def top():
        return {"clan_battle_id": 42, "damage_history": []}

    async def api(path, params, **kwargs):
        return {"start_remain_time": 90, "battle_time": 90}

    clan.get_battle_log, clan.get_clanbattle_top = logs, top
    clan.client = SimpleNamespace(callapi=api)
    assert await asyncio.gather(clan.sync_final_records(clan.event), clan.sync_final_records(clan.event)) == [True, True]
    assert [row[7] for row in committed] == [2]


async def test_cancel_and_restore_preserve_only_current_event_summary_recipient(clanbattle, monkeypatch):
    from src.plugins.priconne.clanbattle.period import BattlePeriod

    monkeypatch.setattr(clanbattle.time, "time", lambda: 1001)
    monkeypatch.setattr(clanbattle, "clanbattle_info", {10001: SimpleNamespace(event=BattlePeriod(42, 1000, 2000))})
    monkeypatch.setattr(clanbattle, "run_group", {})
    clanbattle._set_monitor_registered(10001, 10000, 123)
    clanbattle._set_monitor_stopped(10001)
    saved = json.loads(json.dumps(clanbattle.run_group))
    clanbattle._restore_run_group(saved)
    assert clanbattle.run_group == {10001: {"summary": {"period_id": 42, "self_id": "10000"}}}


async def test_failed_record_batch_keeps_watermark_retryable(clanbattle):
    from src.plugins.priconne.clanbattle.model import ClanBattle

    clan = ClanBattle(10001)
    clan.loop_num = 1
    clan.clan_battle_id = 9
    committed = []

    async def latest():
        return 0

    async def commit(rows):
        committed.extend(rows)

    clan.record = SimpleNamespace(get_latest_time=latest, add_record=commit)
    battles = [{"battle_end_time": moment, "battle_type": 1, "target_viewer_id": 123,
                "user_name": "成员", "order_num": 1, "lap_num": 30, "total_damage": 100,
                "battle_log_id": moment, "units": []} for moment in (1000, 1001)]

    async def logs(page):
        return {"max_page": 1, "battle_list": battles}

    failing = True

    async def api(path, params, **kwargs):
        if failing and params["battle_log_id"] == 1001:
            raise RuntimeError("timeline temporarily unavailable")
        return {"start_remain_time": 90, "battle_time": 90}

    clan.get_battle_log = logs
    clan.client = SimpleNamespace(callapi=api)
    assert await clan.add_record([], 1) is False
    assert committed == []
    failing = False
    assert await clan.add_record([], 1) is True
    assert [row[7] for row in committed] == [1000, 1001]


async def test_roster_snapshot_preserves_same_name_game_ids(clanbattle, monkeypatch):
    from src.plugins.priconne.clanbattle import model

    clan = model.ClanBattle(10001)
    clan.clan_id = 9
    saved = []

    async def api(*args, **kwargs):
        return {"clan": {"members": [{"name": "同名", "viewer_id": 1},
                                      {"name": "同名", "viewer_id": 2}]}}

    async def config(*args):
        return {"kpi": {"1": 2}}

    async def save(path, config):
        saved.append(config)

    clan.client = SimpleNamespace(callapi=api)
    monkeypatch.setattr(model, "load_config", config)
    monkeypatch.setattr(model, "write_config", save)
    await clan.save_member("ignored.json")
    assert saved[0]["member_by_id"] == {"1": "同名", "2": "同名"}
    assert saved[0]["kpi"] == {"1": 2} and saved[0]["member_updated_at"] > 0


@pytest.fixture()
def clanbattle(app, monkeypatch, tmp_path):
    from src.plugins.priconne import clanbattle as module
    monkeypatch.setattr(module.model, "clan_path", str(tmp_path))
    return module


def _snapshot():
    return {
        "time": 1_777_777_777,
        "rank": 42,
        "boss": "当前进度：D面3阶段\n30周目1王: HP: 1/2 50%",
    }


@pytest.fixture()
def status_canvas(monkeypatch):
    from src.plugins.priconne.clanbattle import reports

    captured = {}

    def render(title, metadata, cards, sections, note):
        captured.update(cards=cards, sections=sections)
        return "[CQ:image,file=test-status.png]"

    monkeypatch.setattr(reports, "_report_image", render)
    return captured


@pytest.fixture(autouse=True)
def snapshot_period(clanbattle, monkeypatch):
    from src.plugins.priconne.clanbattle.period import BattlePeriod

    moment = _snapshot()["time"]

    async def schedule(*args, **kwargs):
        return BattlePeriod(42, moment - 3600, moment + 86400 * 4)

    monkeypatch.setattr(clanbattle, "get_period", schedule)


async def test_monitor_switch_clears_old_registrations_once_and_binds_record_queries(clanbattle, monkeypatch):
    from src.plugins.priconne.clanbattle import model
    from src.plugins.priconne.clanbattle.period import BattlePeriod

    old = BattlePeriod(41, 100, 200)
    current = BattlePeriod(42, 1000, 2000)
    clan = model.ClanBattle(11)
    clan.event = old
    clan.notice_dao = ["上一期提醒"]
    clan.boss[0].current_hp = 99
    config, cleared, saved = {"clan_battle_id": 41, "kpi": {"1": 2}}, [], []

    async def schedule(**kwargs):
        assert kwargs == {"event_id": 42}
        return current

    async def load(path):
        return dict(config)

    async def clear(group):
        cleared.append(group)

    async def write(path, value):
        config.update(value)
        saved.append(dict(value))

    monkeypatch.setattr(model, "get_period", schedule)
    monkeypatch.setattr(model, "load_config", load)
    monkeypatch.setattr(model, "write_config", write)
    monkeypatch.setattr(model, "clear_period_registrations", clear)
    await clan.bind_period(42)
    assert cleared == [11] and clan.notice_dao == [] and clan.boss[0].current_hp == 0
    assert clan.record.period == current and clan.clan_battle_id == 42 and clan.latest_time == 999
    assert saved == [{"clan_battle_id": 42, "kpi": {"1": 2}, "battle_start": 1000, "battle_end": 1999}]
    await clan.bind_period(42)
    restarted = model.ClanBattle(11)
    await restarted.bind_period(42)
    assert cleared == [11] and len(saved) == 1
    clan.init_database()
    await clan.bind_period(42)
    assert clan.record.period == current


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


async def test_status_is_offline_immediately_after_cancel(clanbattle, monkeypatch, status_canvas):
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
    bot = SimpleNamespace(send=lambda event, message: fake_safe_send(None, event, message))
    event = SimpleNamespace(group_id=10001, user_id=20001)

    await clanbattle.delete_monitor(bot, event)
    await clanbattle.daostate(bot, event)

    assert len(sent) == 1
    assert sent[0] == "[CQ:image,file=test-status.png]"
    assert status_canvas["cards"][1][0] == "42名"
    assert status_canvas["cards"][3][0] == "历史"


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


async def test_offline_status_uses_persisted_snapshot(clanbattle, monkeypatch, status_canvas):
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
    bot = SimpleNamespace(send=lambda event, message: fake_safe_send(None, event, message))
    event = SimpleNamespace(group_id=10001)

    await clanbattle.daostate(bot, event)

    assert len(sent) == 1
    assert sent[0] == "[CQ:image,file=test-status.png]"
    assert status_canvas["cards"][1][0] == "42名" and status_canvas["cards"][3][0] == "历史"
    assert status_canvas["sections"][1][2] == [[snapshot["boss"]]]


async def test_offline_status_without_snapshot_keeps_existing_prompt(clanbattle, monkeypatch, status_canvas):
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

    assert sent == ["[CQ:image,file=test-status.png]"]
    assert status_canvas["cards"][3][0] == "待刷新"
    assert status_canvas["sections"][1][2] == [["暂无本期状态"]]


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


@pytest.mark.parametrize(('kind', 'probe_result'), [
    ('network', (True, None, '')),
    ('network', (False, None, '')),
    ('game', (True, None, '')),
    ('other', (False, 5, 'temporary')),
])
async def test_transient_monitor_errors_backoff_silently_without_relogin(
    clanbattle, monkeypatch, kind, probe_result
):
    import httpx
    from src.plugins.priconne.pcrclient import ApiException

    clan = _failing_clan(error_count=2)
    error = ApiException('temporary', 5) if kind == 'game' else RuntimeError('poll failed')
    if kind == 'network':
        error = ApiException('wrapped', 501)
        error.__cause__ = httpx.ReadError('')

    async def top():
        raise error

    async def probe():
        return probe_result

    clan.get_clanbattle_top, clan.probe_session = top, probe
    monkeypatch.setattr(clanbattle, 'clanbattle_info', {10001: clan})
    monkeypatch.setattr(clanbattle, 'run_group', {10001: {'self_id': 1, 'qq_id': 2}})
    sent, delays = [], []

    async def save():
        return True

    async def send(bot, event, group_id, message):
        sent.append(message)

    async def sleep(delay):
        delays.append(delay)
        assert sent == []
        assert clanbattle.run_group[10001]['qq_id'] == 2
        clanbattle._invalidate_monitor_loop(10001)
        clanbattle._set_monitor_stopped(10001)

    async def reconnect(*args):
        pytest.fail('temporary errors must not re-login')

    monkeypatch.setattr(clanbattle, '_save_run_group', save)
    monkeypatch.setattr(clanbattle, '_loop_send', send)
    monkeypatch.setattr(clanbattle, '_reconnect_once', reconnect)
    monkeypatch.setattr(clanbattle.asyncio, 'sleep', sleep)
    await clanbattle._monitor_loop(None, None, 10001, 2, 'account.json', 1, 7)
    assert delays == [8]
    assert sent == ['#编号HN0007监控已关闭']
    assert not clanbattle.run_group and clan.loop_check is False


@pytest.mark.parametrize(('code', 'expected'), [(501, None), (5, 5), (3, 3)])
async def test_probe_distinguishes_internal_transport_code_from_game_status(clanbattle, code, expected):
    from src.plugins.priconne.pcrclient import ApiException

    async def api(*args, **kwargs):
        assert kwargs['noerr'] is False
        raise ApiException('failed', code)

    clan = clanbattle.ClanBattle(10001)
    clan.client = SimpleNamespace(callapi=api)
    reachable, status, message = await clan.probe_session()
    assert reachable is False and status == expected


@pytest.mark.parametrize('status', [5, 3])
async def test_transient_record_failure_reaches_monitor_without_committing_batch(clanbattle, status):
    from src.plugins.priconne.pcrclient import ApiException

    clan = clanbattle.ClanBattle(10001)
    clan.loop_num = 1
    clan.clan_battle_id = 9

    async def latest():
        return 0

    async def commit(rows):
        pytest.fail('incomplete batch must not be committed')

    async def api(*args, **kwargs):
        assert kwargs['noerr'] is False
        raise ApiException('temporary', status)

    clan.record = SimpleNamespace(get_latest_time=latest, add_record=commit)
    clan.client = SimpleNamespace(callapi=api)
    with pytest.raises(ApiException) as caught:
        await clan.add_record([], 1)
    assert caught.value.code == status


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

async def test_matched_kill_history_still_fetches_damage_report_and_reuses_verified_cache(clanbattle):
    from src.plugins.priconne.clanbattle.model import ClanBattle
    from src.plugins.priconne.clanbattle.period import BattlePeriod

    clan = ClanBattle(10001)
    clan.event, clan.clan_battle_id, clan.clan_id, clan.loop_num = BattlePeriod(42, 1000, 2000), 42, 8, 1
    rows = [dict(id=i, pcrid=i, name='成员', time=1000+i, lap=42, boss='1', damage=raw,
                 flag=0, battle_log_id=i, remain_time=90, battle_time=90, settlement=None, day_complete=True)
            for i, raw in ((1, 900), (2, 500))]
    calls = []

    async def records(start, end):
        return deepcopy(rows)

    async def save(changed):
        for item in changed:
            rows[item['id'] - 1]['settlement'] = item['settlement']

    async def api(path, params, **kwargs):
        assert path == '/clan_battle/damage_report' and kwargs['noerr'] is False
        calls.append(params)
        return dict(max_hp=1000, damage_report=[dict(viewer_id=1, damage=900), dict(viewer_id=2, damage=100)])

    clan.record = SimpleNamespace(get_settlement_records=records, save_settlement_facts=save)
    clan.client = SimpleNamespace(callapi=api)
    history = [dict(viewer_id=i, lap_num=42, order_num=1, create_time=1000+i,
                    history_id=i, damage=raw, kill=i == 2) for i, raw in ((1, 900), (2, 500))]
    for _ in range(2):
        await clan._enrich_records(history, [dict(lap_num=42, order_num=1, max_hp=1000)], 1)
        kill = clan.settlements[('2', 42, '1', 1002)]
        assert kill['damage'] == 500 and kill['effective_damage'] == 100
        assert kill['hp_before'] == 100 and kill['extended_seconds'] == 90
    assert len(calls) == 1

async def test_collection_persists_ownership_and_proves_overlap_without_duplicate_inserts(clanbattle, monkeypatch):
    from src.plugins.priconne.clanbattle.period import BattlePeriod
    from src.plugins.priconne.clanbattle import model

    clan = model.ClanBattle(10001)
    start = 1790197200
    clan.event, clan.clan_battle_id, clan.loop_num = BattlePeriod(42, start, start + 86400), 42, 1
    saved, timeline_calls, page_calls = [], [], []

    def battle(log, owner):
        unit = dict(unit_id=100+log, viewer_id=owner, unit_level=100, damage=100,
                    unit_rarity=5, promotion_level=30, unique_equip_slot=[])
        return dict(battle_end_time=start+log*10, battle_type=1, target_viewer_id=123, user_name='成员',
                    order_num=1, lap_num=30, total_damage=100, battle_log_id=log, units=[unit])

    pages = {1: [battle(1, 123)], 2: [battle(2, None)]}

    async def latest():
        return max((row[2] for row in saved), default=0)

    async def existing(first, last):
        return [dict(pcrid=r[0], time=r[2], lap=r[3], boss=str(r[4]), battle_log_id=r[7])
                for r in saved if first <= r[2] < last]

    async def insert(rows):
        saved.extend(rows)

    async def logs(page):
        page_calls.append(page)
        return dict(max_page=2, battle_list=pages[page])

    async def api(path, params, **kwargs):
        timeline_calls.append(params['battle_log_id'])
        if params['battle_log_id'] == 4:
            raise RuntimeError('partial page batch')
        return dict(start_remain_time=90, battle_time=90)

    clan.record = SimpleNamespace(get_latest_time=latest, get_report_records=existing, add_record=insert)
    clan.client, clan.get_battle_log = SimpleNamespace(callapi=api), logs
    monkeypatch.setattr(model, 'timestamp', lambda: start+500)
    assert await clan._add_record([], 1) is True
    assert clan.record_coverage['complete'] is True and len(saved) == 2
    assert saved[0][40]['unit_owners'] == [dict(unit_id=101, viewer_id=123)]
    assert saved[0][40]['owners_complete'] is True
    assert saved[1][40]['unit_owners'][0]['viewer_id'] is None
    assert saved[1][40]['owners_complete'] is False
    pages[2].append(battle(3, 999))
    monkeypatch.setattr(model, 'timestamp', lambda: start+600)
    assert await clan._add_record([], 1) is True
    assert [row[7] for row in saved] == [1, 2, 3] and timeline_calls == [1, 2, 3]
    assert clan.record_coverage['through'] == start+600
    before = deepcopy(clan.record_coverage)
    pages[2].append(battle(4, 123))
    monkeypatch.setattr(model, 'timestamp', lambda: start+700)
    assert await clan._add_record([], 1) is False
    assert clan.record_coverage == before and [row[7] for row in saved] == [1, 2, 3]

    async def cancelled_insert(rows):
        saved.extend(rows)
        clan.loop_num += 1

    async def recovered_api(*args, **kwargs):
        return dict(start_remain_time=90, battle_time=90)

    clan.record.add_record = cancelled_insert
    clan.client.callapi = recovered_api
    with pytest.raises(clanbattle.CancleError):
        await clan._add_record([], 1)
    assert clan.record_coverage == before
