from datetime import datetime, timedelta, timezone
import json

import pytest


@pytest.fixture()
def reports(app):
    from src.plugins.priconne.clanbattle import reports

    return reports


def ts(day, hour, minute=0):
    return int(datetime(2026, 10, day, hour, minute, tzinfo=timezone(timedelta(hours=8))).timestamp())


def record(uid, time, flag=0, name="同名"):
    return {"pcrid": uid, "name": name, "time": time, "flag": flag, "lap": 30, "boss": "4"}


@pytest.mark.parametrize("condition", ["fresh", "stale", "foreign", "legacy"])
def test_reservation_lap_warning_requires_fresh_same_event_progress(reports, monkeypatch, condition):
    from src.plugins.priconne.clanbattle.period import BattlePeriod

    now, event = ts(3, 19), BattlePeriod(42, ts(1, 5), ts(6, 0))
    snapshot = {"time": now, "clan_battle_id": 42, "bosses": [
        dict(order=order, lap_num=40, stage="D", current_hp=1, max_hp=2, available=True)
        for order in range(1, 6)]}
    if condition == "stale":
        snapshot["time"] -= 121
    elif condition == "foreign":
        snapshot["clan_battle_id"] = 41
    elif condition == "legacy":
        snapshot.pop("bosses")
    captured = []
    monkeypatch.setattr(reports, "_report_image", lambda *args: captured.append(args) or "图片")
    reports.registration_report("subscribe", {1: [(1, 39, "尾刀"), (2, 0, ""), (3, 42, "等待")]},
                                {}, now, event, 456, snapshot, True)
    rows, actions = captured[0][3][0][2], captured[0][3][-1][2]
    assert len(actions) <= 2
    if condition == "fresh":
        assert "已过周目" in rows[1][4] and rows[0][4] == "当前周目" and "后续周目" in rows[2][4]
        assert "取消预约 1" in str(actions)
    else:
        assert all(row[4] == "待核验" for row in rows) and "已过周目" not in str(captured)


def test_tree_list_filters_period_and_future_and_orders_oldest_first(reports, monkeypatch):
    from src.plugins.priconne.clanbattle.period import BattlePeriod

    now, event = ts(3, 19), BattlePeriod(42, ts(1, 5), ts(6, 0))
    captured = []
    monkeypatch.setattr(reports, "_report_image", lambda *args: captured.append(args) or "图片")
    reports.registration_report("tree", {1: [(1, event.start - 1, "旧期"), (2, now + 1, "未来"),
                                            (3, now, "刚登记")], 5: [(4, event.start, "久等")]},
                                {}, now, event, 456)
    rows = captured[0][3][0][2]
    assert [row[1] for row in rows] == ["QQ 4", "QQ 3"]
    assert rows[0][0] == "5王" and rows[1][2].startswith("0秒")
    assert "旧期" not in str(captured) and "未来" not in str(captured)


@pytest.mark.parametrize("kind", ["subscribe", "tree"])
def test_empty_registration_list_gives_usable_command(reports, monkeypatch, kind):
    from src.plugins.priconne.clanbattle.period import BattlePeriod

    captured = []
    monkeypatch.setattr(reports, "_report_image", lambda *args: captured.append(args) or "图片")
    reports.registration_report(kind, {}, {}, ts(3, 19), BattlePeriod(42, ts(1, 5), ts(6, 0)), 456)
    assert ("预约 3" if kind == "subscribe" else "挂树 3") in str(captured[0][3][-1][2])


async def test_period_uses_fifth_day_midnight_instead_of_monthly_display_end(app, monkeypatch, tmp_path):
    import sqlite3
    from src.plugins.priconne.clanbattle import period

    path = tmp_path / "schedule.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE clan_battle_schedule (clan_battle_id INTEGER, start_time TEXT, end_time TEXT)")
        db.executemany("INSERT INTO clan_battle_schedule VALUES (?, ?, ?)", [
            (1092, "2026/09/24 5:00:00", "2026/10/24 4:59:59"),
            (1093, "2026/10/24 5:00:00", "2026/11/24 4:59:59"),
        ])
    monkeypatch.setattr(period, "SCHEDULE_DB", path)
    sep = await period.get_period(ts(10, 12))
    assert sep.id == 1092
    assert datetime.fromtimestamp(sep.end - 1, period.GAME_TZ).isoformat() == "2026-09-28T23:59:59+08:00"
    assert sep.active(sep.start) and not sep.active(sep.start - 1)
    assert sep.active(sep.end - 1) and not sep.active(sep.end)
    assert [sep.quota(sep.start + days * 86400) for days in range(6)] == [3, 6, 9, 12, 15, 15]
    assert sep.quota(sep.start - 1) == 0 and "已结束" in sep.label(sep.end)
    oct_start = int(datetime(2026, 10, 24, 5, tzinfo=period.GAME_TZ).timestamp())
    assert (await period.get_period(oct_start - 1)).id == 1092
    assert (await period.get_period(oct_start)).id == 1093
    with pytest.raises(ValueError, match="更新wiki数据库"):
        await period.get_period(event_id=9999)
    monkeypatch.setattr(period, "SCHEDULE_DB", tmp_path / "missing.db")
    with pytest.raises(ValueError, match="未使用其他期"):
        await period.get_period(ts(10, 12))


def test_ended_daily_report_does_not_invent_today_quota_and_habits_span_events(reports, monkeypatch):
    from src.plugins.priconne.clanbattle.period import BattlePeriod

    event = BattlePeriod(42, ts(1, 5), ts(6, 0))
    message = reports.daily_report([], {"member_by_id": {"1": "成员"}}, ts(10, 12), event)
    assert "已结束" in message and "整期15刀" in message and "参考未完成" not in message
    images = []
    monkeypatch.setattr(reports, "_report_image", lambda *args: images.append(args) or "图片")
    message = reports.daily_report([], {}, ts(5, 23), event)
    assert message == "图片" and "05:00 至 10-05 23:59:59" in images[0][1]
    records = [record(1, int(datetime(2026, month, 24, 21, tzinfo=reports.GAME_TZ).timestamp()))
               for month in (8, 9, 10)]
    captured = []
    monkeypatch.setattr(reports, "_report_image", lambda title, metadata, cards, sections, note: captured.extend(sections[0][2]) or "表格")
    message = reports.preference_report(records, {"member_by_id": {"1": "成员"}}, ts(28, 12))
    assert captured[0][1] == "21–23 3/3天" and captured[0][3] == 3
    assert "跨期历史" in message and "08-24" in message and "近28" not in message


def test_daily_members_keep_same_names_separate_and_show_unobserved_members(reports):
    rows = reports.daily_members(
        [record(1, ts(10, 21)), record(1, ts(10, 22), 1),
         record(1, ts(10, 23), 0.5), record(2, ts(10, 20)),
         record(4, ts(10, 19), 9)],
        {"1": "同名", "2": "同名", "3": "零记录"},
    )
    players = {p["pcrid"]: p for p in rows}
    assert (players["1"]["full"], players["1"]["tail"], players["1"]["comp"]) == (1, 1, 1)
    assert players["1"]["knife"] == 2 and players["1"]["remaining"] == 1
    assert players["2"]["knife"] == 1
    assert players["3"]["latest"] is None and "今日无记录，需确认" in players["3"]["notes"]
    assert players["4"]["knife"] == 0 and players["4"]["notes"] == ["名册外成员", "刀型待确认"]


def test_preference_counts_days_instead_of_repeated_compensation_and_marks_ties(reports):
    records = [record(1, ts(day, hour)) for day in (8, 9, 10) for hour in (21, 23)]
    records += [record(1, ts(8, 21, 10), 1), record(1, ts(8, 21, 11), 0.5)]
    player = reports.preference_members(records, {"1": "成员"})[0]
    assert player["days"] == 3 and player["records"] == 8
    assert player["slots"] == {8: 3, 9: 3}
    assert player["common"] == [[8, 9]]
    assert "并列" in reports._slot_text(player["common"][0])


def test_preference_uses_five_am_boundary_and_does_not_invent_low_sample_patterns(reports, monkeypatch):
    records = [record(1, ts(9, 23)), record(1, ts(10, 4, 59)), record(1, ts(10, 5))]
    players = reports.preference_members(records, {"1": "成员", "2": "无记录"})
    assert players[0]["days"] == 2
    assert players[0]["slots"] == {9: 1, 11: 1, 0: 1}
    captured = []
    monkeypatch.setattr(reports, "_report_image", lambda title, metadata, cards, sections, note: captured.extend(sections[0][2]) or "表格")
    reports.preference_report(records, {"member_by_id": {"1": "成员", "2": "无记录"}}, ts(10, 12))
    assert captured[0][1] == "样本不足" and captured[1][1] == "无样本"


def test_legacy_roster_and_missing_metadata_are_explicit(reports, monkeypatch):
    captured = []
    monkeypatch.setattr(reports, "_report_image", lambda *args: captured.append(args) or "表格")
    message = reports.daily_report([], {"member": {"旧成员": 123}}, ts(10, 12))
    assert message == "表格" and "名册待刷新" in captured[0][-1]
    rows = captured[0][3][0][2]
    assert rows[0][0]["items"] == ["暂无记录"] and rows[0][1]["items"] == ["旧成员"] and rows[0][2] == 1
    assert "同步状态待核验" in reports.report_status({"time": ts(10, 12)}, True, ts(10, 12))


@pytest.mark.parametrize(("hp", "zone"), [(301, "健康"), (300, "准备合刀"), (201, "准备合刀"),
                                        (200, "建议合刀"), (101, "建议合刀"), (100, "收尾参考"), (99, "烂尾"), (0, "已击破")])
def test_health_boundaries_respect_one_more_median_attack(reports, hp, zone):
    boss = dict(current_hp=hp, max_hp=500)
    cell = reports.boss_hp_cell(boss, 100, True)
    assert cell["zone"] == zone
    assert cell["ratio"] == hp / 500
    if zone == "健康":
        assert hp - 100 > 200 and cell["color"] == "#22C55E"
    if zone == "烂尾":
        assert cell["color"] == "#EF4444"
    if hp:
        assert reports.boss_hp_cell(boss, 100, False)["color"] == "#8793A6"


def test_health_uses_only_current_valid_samples_and_has_distinct_blue_shades(reports, monkeypatch):
    from src.plugins.priconne.clanbattle.period import BattlePeriod

    event, now = BattlePeriod(42, ts(1, 5), ts(6, 0)), ts(3, 19)
    bosses = [dict(order=order, lap_num=30, stage="D", current_hp=150, max_hp=500,
                   available=True, fighter_num=0) for order in range(1, 6)]
    snapshot = dict(time=now, clan_battle_id=42, bosses=bosses, records_synced_at=now, record_sync_ok=True)
    samples = [dict(record(i % 2, now - 60), boss="1", damage=100, battle_log_id=i + 1) for i in range(4)]
    samples += [dict(samples[0], time=event.start - 1, battle_log_id=10),
                dict(samples[0], time=now + 1, battle_log_id=11),
                dict(samples[0], flag=None, battle_log_id=12)]
    captured = []
    monkeypatch.setattr(reports, "_report_image", lambda *args: captured.append(args) or "图片")
    reports.status_report(snapshot, True, now, event, 456, records=samples)
    assert captured[-1][3][1][2][0][1]["color"] == "#8793A6"
    samples.append(dict(samples[0], battle_log_id=13))
    reports.status_report(snapshot, True, now, event, 456, records=samples)
    assert captured[-1][3][1][2][0][1]["zone"] == "建议合刀"
    snapshot["records_synced_at"] = now - 121
    reports.status_report(snapshot, True, now, event, 456, records=samples)
    assert captured[-1][3][1][2][0][1]["color"] == "#8793A6"
    snapshot["records_synced_at"] = now
    snapshot.pop("record_sync_ok")
    reports.status_report(snapshot, True, now, event, 456, records=samples)
    assert captured[-1][3][1][2][0][1]["color"] == "#8793A6"
    shades = [reports.boss_hp_cell(dict(current_hp=hp, max_hp=400), 100, True)["color"] for hp in (290, 230, 190, 120, 100)]
    assert len(set(shades)) == 5


def test_daily_grouping_keeps_unknown_and_non_roster_separate_and_disambiguates_names(reports, monkeypatch):
    from src.plugins.priconne.clanbattle.period import BattlePeriod

    event, now = BattlePeriod(42, ts(1, 5), ts(6, 0)), ts(3, 19)
    rows = [record(1, now - i) for i in range(3)] + [record(2, now), record(2, now, 1),
            record(3, now, 9), record(99, now), record(4, now + 1), record(4, ts(2, 19))]
    captured = []
    monkeypatch.setattr(reports, "_report_image", lambda *args: captured.append(args) or "图片")
    reports.daily_report(rows, {"member_by_id": {str(i): "同名" for i in range(1, 5)}, "member_updated_at": now}, now, event)
    rendered = {row[0]["items"][0]: row for row in captured[0][3][0][2]}
    assert captured[0][2] == [] and set(rendered) == {"3刀", "1.5刀", "暂无记录", "待核验", "名册外"}
    assert rendered["暂无记录"][1]["items"] == ["同名 (4)"]
    assert rendered["待核验"][1]["items"] == ["同名 (3)"]
    assert sum(row[2] for row in rendered.values()) == 5


def test_status_separates_fighters_from_applicants_and_limits_action_hints(reports, monkeypatch):
    from src.plugins.priconne.clanbattle.period import BattlePeriod

    period, now = BattlePeriod(42, ts(1, 5), ts(6, 0)), ts(2, 12)
    bosses = [dict(order=order, lap_num=30, stage="D", current_hp=100, max_hp=200,
                   available=True, fighter_num=[0, 1, 3, None, 0][order - 1]) for order in range(1, 6)]
    snapshot = dict(time=now, rank=42, clan_battle_id=42, bosses=bosses, records_synced_at=now, record_sync_ok=True)
    queues = {order: dict(apply=[], tree=[], subscribe=[]) for order in range(1, 6)}
    queues[1]["apply"] = [(uid, now - 10, "[CQ:at,qq=all]") for uid in (1, 2, 3)]
    queues[1]["apply"] += [(90, period.start - 1, "上期残留"), (91, now + 1, "未来登记")]
    queues[2]["tree"] = [(4, now - 60, "等待结算")]
    queues[2]["tree"] += [(92, period.start - 1, "旧挂树")]
    queues[4]["apply"] = [(5, now - 10, reports.encode_declaration(dict(
        event=42, lap=29, hp=100, kind="full", seconds=90, damage=100, note="目标已换周目")))]
    monkeypatch.setattr(reports, "_report_image", lambda title, metadata, cards, sections, note: sections)
    sections = reports.status_report(snapshot, True, now, period, 456, queues, details=True)
    rows = sections[1][2]
    assert [row[3] for row in rows] == [0, 1, 3, "未知", 0]
    assert rows[0][4:6] == [3, 0] and rows[1][4:6] == [0, 1]
    assert "重确认" in rows[3][-1]
    detail = sections[2][2]
    assert [row[1] for row in detail[:3]] == ["QQ 1", "QQ 2", "QQ 3"]
    assert all("留言申请" in row[-1] and "[CQ:at,qq=all]" in row[-1] for row in detail[:3])
    assert "重新申请" in detail[-1][-1]
    assert all(text not in str(sections) for text in ("上期残留", "未来登记", "旧挂树"))
    assert len(sections[-1][2]) == 2
    assert "3王多人挑战" in sections[-1][2][0][0] and "查树" in sections[-1][2][1][0]


@pytest.mark.parametrize("condition", ["expired", "ended", "foreign"])
def test_status_masks_old_or_foreign_live_data_and_gives_relevant_next_step(reports, monkeypatch, condition):
    from src.plugins.priconne.clanbattle.period import BattlePeriod

    period, moment = BattlePeriod(42, ts(1, 5), ts(6, 0)), ts(2, 12)
    bosses = [dict(order=order, lap_num=30, stage="D", current_hp=100, max_hp=200,
                   available=True, fighter_num=2) for order in range(1, 6)]
    snapshot = dict(time=moment, clan_battle_id=41 if condition == "foreign" else 42, rank=999, bosses=bosses)
    now = period.end if condition == "ended" else moment + 121 if condition == "expired" else moment
    queues = {order: dict(apply=[(1, moment, "旧登记")], tree=[], subscribe=[]) for order in range(1, 6)}
    monkeypatch.setattr(reports, "_report_image", lambda title, metadata, cards, sections, note: (cards, sections))
    cards, sections = reports.status_report(snapshot, True, now, period, 456, queues, details=True)
    if condition == "foreign":
        assert cards[1][0] == "—" and sections[1][2] == [["暂无本期状态"]]
    else:
        assert all(row[3:6] == ["未知"] * 3 for row in sections[1][2])
    text = str(sections)
    assert "旧登记" not in text and "申请与挂树" not in text
    if condition == "ended":
        assert "会战复盘" in text and "出刀监控" not in text
    else:
        assert "出刀监控" in text


def test_control_report_separates_queues_and_does_not_infer_offline_challenges(reports, monkeypatch):
    bosses = [{"order": order, "lap_num": 30, "stage": "D", "current_hp": 100,
               "max_hp": 200, "available": True, "fighter_num": 2 if order == 1 else 0}
              for order in range(1, 6)]
    queues = {order: {"apply": [], "subscribe": [], "tree": []} for order in range(1, 6)}
    queues[1] = {"apply": [(7, ts(10, 10), "后登记"), (8, ts(10, 9), "先登记")],
                 "subscribe": [(7, 0, "当前"), (8, 31, "未来")], "tree": []}
    captured = []
    monkeypatch.setattr(reports, "_report_image", lambda title, metadata, cards, sections, note: captured.extend(sections[0][2]) or "表格")
    _, details = reports.control_report(bosses, [], queues, {}, ts(10, 12), True, 42)
    assert captured[0][2] == "战2 申2 约1/1 树0"
    assert details.index("先登记") < details.index("后登记")
    assert "协调结算" in details
    captured.clear()
    _, offline = reports.control_report(bosses, [], queues, {}, ts(10, 12), False, 42)
    assert captured[0][2] == "战未知 申2 约1/1 树0" and "协调结算" not in offline
    assert "有效性需确认" in offline
    assert reports.snapshot_bosses({"bosses": [{"order": "bad"}] * 5}) is None


def declaration(damage=10000000, kind="full", seconds=90, **changes):
    fields = {"event": 42, "lap": 30, "hp": 15000000, "kind": kind,
              "seconds": seconds, "damage": damage, "note": "稳定轴"}
    fields.update(changes)
    return "[出刀申报]" + json.dumps(fields, ensure_ascii=False)


def battle_queues():
    bosses = [{"order": order, "lap_num": 30, "stage": "D", "current_hp": 15000000,
               "max_hp": 20000000, "available": True, "fighter_num": 0} for order in range(1, 6)]
    queues = {order: {"apply": [], "subscribe": [], "tree": []} for order in range(1, 6)}
    return bosses, queues


@pytest.mark.parametrize("text", ["完整 0万", "补偿91秒 450万", "补偿0秒 450万",
                                 "完整 1000-200万", "完整 1000", "[出刀申报]{}"])
def test_declaration_rejects_ambiguous_units_expressions_and_forged_metadata(reports, text):
    with pytest.raises(ValueError):
        reports.parse_declaration_input(text)


def test_declaration_distinguishes_carryover_duration_from_damage_and_preserves_legacy_comments(reports):
    assert reports.parse_declaration_input("补偿60秒 450万 稳定轴") == {
        "kind": "comp", "seconds": 60, "damage": 4500000, "note": "稳定轴"}
    assert reports.parse_declaration_input("完整 1000W")["damage"] == 10000000
    assert reports.parse_declaration_input("请等我十分钟") is None
    assert reports.decode_declaration(declaration(kind="full", seconds=60)) is None


def test_declaration_drops_spent_stale_wrong_target_and_conflicting_knives(reports):
    bosses, queues = battle_queues()
    now = ts(10, 12)
    queues[1]["apply"] = [
        (1, now - 1800, declaration()), (1, now - 10, declaration(damage=9000000)),
        (2, now - 10, declaration(hp=16000000)),
        (3, now - 1801, declaration()), (4, now - 10, declaration(lap=29)),
        (5, now - 10, declaration(event=41)), (6, now - 10, declaration()),
        (7, now - 10, declaration()), (8, now + 1, declaration()),
    ]
    queues[2]["apply"] = [(6, now - 10, declaration())]
    queues[3]["tree"] = [(7, now - 100, "挂树")]
    queues[5]["apply"] = [(9, now - 1800, declaration())]
    applications = reports.declared_applications(bosses, queues, now, True, 42)
    eligible = [row for row in applications[1] if not row["issue"]]
    assert [row["uid"] for row in eligible] == [1]
    assert eligible[0]["declaration"]["damage"] == 9000000
    issues = {row["uid"]: row["issue"] for row in applications[1]}
    assert "血量" in issues[2] and "30分钟" in issues[3] and "周目" in issues[4]
    assert "会战" in issues[5] and "多王" in issues[6] and "挂树" in issues[7]
    assert "时间异常" in issues[8]
    assert applications[5][0]["issue"] == ""
    offline = reports.declared_applications(bosses, queues, now, False, 42)
    assert all(row["issue"] for entries in offline.values() for row in entries)


def test_full_damage_reference_does_not_pool_bosses_stages_or_truncated_knives(reports):
    boss = battle_queues()[0][0]
    samples = [dict(record(i % 2 + 1, ts(10, 10)), boss="1", damage=d, battle_log_id=i + 1)
               for i, d in enumerate((6000000, 8000000, 10000000, 12000000, 14000000))]
    noise = [dict(samples[0], boss="2", battle_log_id=10),
             dict(samples[0], lap=10, battle_log_id=11),
             dict(samples[0], flag=1, battle_log_id=12),
             dict(samples[0], flag=0.5, battle_log_id=13), dict(samples[0], damage=0, battle_log_id=14)]
    reference = reports.full_damage_reference(samples + noise + [samples[0]], boss)
    assert reference == {"count": 5, "players": 2, "median": 10000000, "lower": 8000000}
    assert reports.full_damage_reference(samples[:4], boss)["median"] is None
    assert reports.full_damage_reference([dict(r, pcrid=1) for r in samples], boss)["median"] is None


def test_control_report_combines_history_with_only_valid_declarations(reports, monkeypatch):
    bosses, queues = battle_queues()
    now = ts(10, 12)
    queues[1]["apply"] = [(1, now - 10, declaration(damage=9000000)),
                          (2, now - 10, declaration(hp=16000000))]
    samples = [dict(record(i % 2 + 1, now - 60), boss="1", damage=damage, battle_log_id=i + 1)
               for i, damage in enumerate((6000000, 8000000, 10000000, 12000000, 14000000))]
    tables = []
    monkeypatch.setattr(reports, "_report_image", lambda title, metadata, cards, sections, note: tables.append(sections[0][2]) or "表格")
    _, details = reports.control_report(bosses, samples, queues, {1: "同名", 2: "同名"}, now, True, 42)
    assert len(tables) == 1
    assert tables[0][0][3:7] == ["中1000万/低800万", "2/2", "1人/900万", "600万"]
    assert tables[0][1][3].startswith("样本不足") and tables[0][1][4] == "—"
    assert "同名 (QQ 1)" in details and "同名 (QQ 2)" in details and "血量已变化" in details
    tables.clear()
    reports.control_report(bosses, samples, queues, {}, now, False, 42)
    assert tables[0][0][3:7] == ["中1000万/低800万", "—", "待确认", "—"]
