from copy import deepcopy
from datetime import datetime, timezone, timedelta

import pytest


@pytest.fixture
def settlement(app):
    from src.plugins.priconne.clanbattle import settlement
    return settlement


def row(log, *, uid=1, boss=None, seconds=90, used=90, raw=500, actual=100, killed=True, moment=None, manual=None):
    # 本夹具描述已完整收集的游戏日前缀；缺覆盖场景单独验证。
    meta = {"event_id": 42, "history_damage": actual, "killed": killed, "history_id": log}
    if killed:
        meta["report"] = dict(max_hp=actual, totals={str(uid): actual}, covered_logs=[[str(uid), log]])
    if manual is not None:
        meta["manual_flag"] = manual
    return dict(day_complete=True, pcrid=uid, name="成员", time=moment or 1790823600 + log * 120,
                lap=42, boss=str(boss or log), battle_log_id=log, flag=0,
                remain_time=seconds, battle_time=used, damage=raw, settlement=meta)


def test_daily_pairing_leaves_equally_legal_positions_pending_without_changing_damage(settlement):
    records = [row(1), row(2, raw=400, actual=400, killed=False),
               row(3, raw=200, actual=200, killed=False), row(4, raw=1000),
               row(5, raw=300, actual=300, killed=False)]
    original = deepcopy(records)
    result = settlement.analyse_records(records)
    assert [r["flag"] for r in result] == [1, None, None, 1, .5]
    assert result[4]["carry_source"] == 4
    assert result[1]["carry_source"] is None and result[2]["carry_source"] is None
    assert result[0]["extended_seconds"] == result[3]["extended_seconds"] == 90
    assert sum(map(settlement.knife_weight, result)) == 1.5
    assert all(settlement.uncertain(result[i]) for i in (1, 2))
    assert sum(r["effective_damage"] for r in result) == 1100
    assert sum(r["damage"] for r in result) == 2400 and records == original


@pytest.mark.parametrize(("raw", "expected"), [(500, 90), (430, 90), (400, 88)])
def test_full_duration_kill_uses_existing_compensation_rounding(settlement, raw, expected):
    result = settlement.analyse_records([row(1, raw=raw), row(2, seconds=expected, killed=False, actual=500)])
    assert result[0]["flag"] == 1 and result[0]["extended_seconds"] == expected
    if expected == 90:
        assert result[1]["flag"] is None and result[1]["carry_inventory"]["total"] == (0, 1)
    else:
        assert result[1]["flag"] == .5 and result[1]["carry_source"] == 1


def test_confirmed_compensation_kill_never_generates_another_carry(settlement):
    result = settlement.analyse_records([row(1), row(2, manual=.5, used=30), row(3, actual=500, killed=False)])
    assert result[1]["flag"] == .5 and result[1]["extended_seconds"] == 0
    assert result[1]["carry_source"] == 1
    assert result[2]["flag"] == 0 and result[2]["carry_source"] is None


def test_known_short_carry_can_kill_and_does_not_chain(settlement):
    result = settlement.analyse_records([row(1, raw=100, used=50), row(2, seconds=60, used=30),
                                         row(3, actual=500, killed=False)])
    assert result[0]["extended_seconds"] == 60
    assert result[1]["flag"] == .5 and result[1]["extended_seconds"] == 0
    assert result[2]["flag"] == 0


def test_another_ninety_second_kill_can_be_a_tail_or_a_full_carry(settlement):
    result = settlement.analyse_records([row(1), row(2), row(3, killed=False, actual=500)])
    assert [r["flag"] for r in result] == [1, None, None]
    assert result[1]["extended_seconds"] is None
    assert result[2]["carry_inventory"]["total"] == (0, 2)


def test_carry_pairing_never_crosses_member_or_five_am_boundary(settlement):
    before = int(datetime(2026, 10, 2, 4, 59, tzinfo=timezone(timedelta(hours=8))).timestamp())
    result = settlement.analyse_records([
        row(1, moment=before), row(2, uid=2, moment=before + 20, actual=500, killed=False),
        row(3, moment=before + 60, actual=500, killed=False)])
    assert [r["flag"] for r in result] == [1, 0, 0]


def test_four_ordinary_attacks_are_a_conflict_instead_of_silently_clipped(settlement):
    result = settlement.analyse_records([row(i, killed=False, actual=500) for i in range(1, 5)])
    assert all(r["flag"] is None and "冲突" in r["kind_issue"] for r in result)
    assert all(r["effective_damage"] == 500 for r in result)


@pytest.mark.parametrize("valid_totals", [True, False])
def test_reconstruction_requires_official_per_member_damage_match(settlement, valid_totals):
    records = [row(1, uid=1, boss=1, raw=900), row(2, uid=2, boss=1, raw=500)]
    for r in records:
        r["settlement"] = {"event_id": 42}
    records[0]["settlement"]["report"] = dict(max_hp=1000, totals={"1": 900, "2": 100 if valid_totals else 200})
    result = settlement.analyse_records(records)
    assert [r["effective_damage"] for r in result] == ([900, 100] if valid_totals else [None, None])
    assert [r["damage"] for r in result] == [900, 500]


def test_same_second_has_no_fabricated_global_order(settlement):
    records = [row(1, uid=1, boss=1, raw=900), row(2, uid=2, boss=1, raw=500)]
    records[1]["time"] = records[0]["time"]
    for r in records:
        r["settlement"] = {"event_id": 42}
    records[0]["settlement"]["report"] = dict(max_hp=1000, totals={"1": 900, "2": 100})
    assert all(r["effective_damage"] is None for r in settlement.analyse_records(records))
    for i, r in enumerate(records, 1):
        r["settlement"]["history_id"] = i
    assert [r["effective_damage"] for r in settlement.analyse_records(records)] == [900, 100]


def test_old_time_heuristic_is_not_reused_as_evidence(settlement):
    record = row(1, used=30)
    record.update(flag=1, settlement=None)
    inferred = settlement.analyse_records([record])[0]
    assert inferred["raw_flag"] == 1 and inferred["flag"] is None
    assert inferred["effective_damage"] is None and inferred["extended_seconds"] is None


def test_kill_notice_uses_exact_requested_text_and_never_confuses_unknown_with_zero(settlement):
    record = settlement.analyse_records([row(1)])[0]
    history = dict(name="成员", lap_num=42, order_num=1, kill=1, damage=100)
    assert settlement.battle_notice(history, record) == "成员对42周目1王造成100点伤害并击破（原始伤害500）。获得延长战斗时间90s。"
    assert settlement.battle_notice(history) == (
        "成员对42周目1王造成伤害待核验并击破（原始伤害待核验）。延长战斗时间待核验。")
    record["extended_seconds"] = None
    assert settlement.battle_notice(history, record).endswith("延长战斗时间待核验。")
    record["extended_seconds"] = 0
    assert settlement.battle_notice(history, record) == "成员对42周目1王造成100点伤害并击破（原始伤害500）。"


async def test_current_report_uses_deducted_damage_while_personal_report_preserves_raw(settlement, monkeypatch):
    from src.plugins.priconne.clanbattle import base

    records = settlement.analyse_records([row(1), row(2, actual=500, killed=False)])
    players, damage, score = base.clanbattle_report(records, 15)
    assert damage == 600 and score == 2700 and players[0][2] == .5
    assert players[0][5] == 1
    captured = []
    monkeypatch.setattr(base, "grid2imgb64", lambda rows, columns: captured.append((rows, columns)) or "图片")
    await base.get_cbreport(players, damage, score)
    assert captured[-1][0][0][3:5] == ["600", "2700"]
    await base.get_plyerreport([dict(record, history_id=str(record["battle_log_id"])) for record in records])
    assert sum(int(row[2]) for row in captured[-1][0]) == 1000
    unknown = dict(records[0], flag=None, effective_damage=None, kind_issue="待核验")
    players, damage, score = base.clanbattle_report([unknown], 15)
    await base.get_cbreport(players, damage, score)
    assert captured[-1][0][0][-2:] == ["—", "—"]

@pytest.mark.parametrize('evidence', ['verified', 'missing', 'mismatch'])
def test_real_overflow_requires_hp_verification_despite_raw_damage_in_history(settlement, evidence):
    raw = [161419057, 300435529, 289500524, 329475376, 305902692]
    maximum, remaining = 1360000000, 279169514
    records = [row(i, uid=i, boss=2, raw=damage, actual=damage, killed=i == 5)
               for i, damage in enumerate(raw, 1)]
    for item in records:
        item['lap'] = 39
        item['settlement'].pop('report', None)
        item['settlement']['max_hp'] = maximum
    records[-1]['name'] = '妮妮szbwdz'
    if evidence != 'missing':
        totals = {str(i): amount for i, amount in enumerate(raw[:-1] + [remaining], 1)}
        if evidence == 'mismatch':
            totals['5'] += 1
        records[0]['settlement']['report'] = dict(max_hp=maximum, totals=totals,
                                                 covered_logs=[[str(i), i] for i in range(1, 6)])
    original = deepcopy(records)
    result = settlement.analyse_records(records)
    kill = result[-1]
    assert records == original and [r['damage'] for r in result] == raw
    if evidence == 'verified':
        assert sum(r['effective_damage'] for r in result) == maximum
        assert kill['effective_damage'] == kill['hp_before'] == remaining
        assert kill['extended_seconds'] == 28
        history = dict(name='妮妮szbwdz', lap_num=39, order_num=2, kill=1, damage=raw[-1])
        assert settlement.battle_notice(history, kill) == (
            '妮妮szbwdz对39周目2王造成279169514点伤害并击破（原始伤害305902692）。获得延长战斗时间28s。')
    else:
        assert kill['effective_damage'] is None and kill['hp_before'] is None
        assert kill['extended_seconds'] is None and settlement.uncertain(kill)


def test_verified_kill_without_overflow_can_legitimately_return_twenty_seconds(settlement):
    result = settlement.analyse_records([row(1, raw=100, actual=100, used=90)])[0]
    assert result['effective_damage'] == result['damage'] == 100
    assert result['hp_before'] == 100 and result['extended_seconds'] == 20

def test_legacy_metadata_uses_query_event_context_for_same_day_carry_sources(settlement):
    first = row(1, raw=100, actual=100, used=82)
    first['settlement'].pop('event_id')
    first['event_id'] = 42
    second = row(2, seconds=28, raw=500, actual=500, killed=False)
    result = settlement.analyse_records([first,second])
    assert result[0]['extended_seconds'] == 28
    assert result[1]['flag'] == .5 and result[1]['carry_source'] == 1
