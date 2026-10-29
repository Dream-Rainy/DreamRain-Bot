from datetime import datetime, timedelta, timezone
import json

import pytest


def ts(day, hour=19, minute=0, second=0):
    return int(datetime(2026, 10, day, hour, minute, second, tzinfo=timezone(timedelta(hours=8))).timestamp())


@pytest.fixture()
def dispatch(app):
    from src.plugins.priconne.clanbattle import dispatch
    return dispatch


@pytest.fixture()
def period(app):
    from src.plugins.priconne.clanbattle.period import BattlePeriod
    return BattlePeriod(42, ts(24, 5), ts(29, 0))


def record(uid, time, boss=1, damage=10000000, log=None):
    return {"pcrid": uid, "name": "同名", "time": time, "boss": str(boss), "lap": 30,
            "damage": damage, "flag": 0, "battle_log_id": log}


def config(*uids):
    return {"member_by_id": {str(uid): "同名" for uid in uids}}


def battle():
    bosses = [{"order": n, "lap_num": 30, "stage": "D", "current_hp": 15000000,
               "max_hp": 20000000, "fighter_num": 0, "available": True} for n in range(1, 6)]
    queues = {n: {"apply": [], "subscribe": [], "tree": []} for n in range(1, 6)}
    return bosses, queues


def test_uncertain_knife_is_never_a_dispatch_capacity_or_complete_knife_sample(dispatch, period):
    now = ts(28)
    rows = [record(1, ts(26), log=1), record(1, ts(27), log=2),
            dict(record(1, now - 60, log=3), flag=None, kind_issue="刀型待核验")]
    bosses, queues = battle()
    data = dispatch.build_dispatch(rows, config(1), now, period, {"123": "1"}, bosses, queues, True)
    player = data["members"][0]
    assert player["blocked"] == "刀型待核验" and player in data["unplanned"]
    assert not any(window["members"] for window in data["windows"])


def declared(uid, now, damage=10000000, **changes):
    fields = dict(event=42, lap=30, hp=15000000, kind="full", seconds=90, damage=damage, note="")
    fields.update(changes)
    return uid, now - 10, "[出刀申报]" + json.dumps(fields)


def test_current_event_filters_old_future_departed_and_duplicate_records(dispatch, period):
    now = ts(28)
    rows = [record(1, ts(24), log=1), record(1, ts(24, 20), log=2), record(1, ts(25), log=3),
            record(1, ts(23), log=4), record(1, ts(28, 20), log=5), record(99, ts(28), log=6)]
    rows.append(rows[0])
    data = dispatch.build_dispatch(rows, config(1, 2), now, period)
    players = {p['pcrid']: p for p in data['members']}
    assert set(players) == {'1', '2'}
    assert data['prior_days'] == 4 and players['1']['hits'] == 2
    assert players['1']['remaining'] == 3 and not players['1']['recent']
    assert [p['pcrid'] for p in data['active_members']] == ['1']


def test_game_day_boundary_first_day_and_last_second(dispatch, period):
    rows = [record(1, ts(24, 3)), record(1, ts(25, 4)), record(1, ts(26, 4, 40))]
    first = dispatch.build_dispatch(rows, config(1), ts(24, 6), period)
    assert first['prior_days'] == 0 and not first['active_members']
    before = dispatch.build_dispatch(rows, config(1), ts(26, 4, 50), period)
    assert before['prior_days'] == 1
    assert before['members'][0]['remaining'] == 2 and before['members'][0]['recent']
    assert before['windows'][0]['end'] == ts(26, 5)
    after = dispatch.build_dispatch(rows, config(1), ts(26, 5), period)
    assert after['prior_days'] == 2 and after['members'][0]['remaining'] == 3
    last = dispatch.build_dispatch([], config(1), ts(28, 23, 59, 59), period)
    assert last['active'] and len(last['windows']) == 1
    assert last['windows'][0]['label'] == '23:59–23:59:59' and last['windows'][0]['end'] == period.end
    ended = dispatch.build_dispatch(rows, config(1), period.end, period)
    assert not ended['active'] and ended['windows'] == [] and ended['pairs'] == []


def test_history_pairs_do_not_claim_hp_or_assign_people_twice(dispatch, period):
    rows = [record(uid, ts(day), boss=boss, log=uid * 1000 + boss * 100 + day)
            for uid in (1, 2, 3, 4) for day in (24, 25) for boss in (1, 2)]
    bosses, queues = battle()
    data = dispatch.build_dispatch(rows, config(1, 2, 3, 4), ts(26), period, {}, bosses, queues, True)
    assert len(data['pairs']) == 2
    assert all(not pair['declared'] and pair['gap'] is None for pair in data['pairs'])
    pair_members = [p['pcrid'] for pair in data['pairs'] for p in pair['members']]
    assert len(set(pair_members)) == len(pair_members) == 4
    planned = [p['pcrid'] for window in data['windows'] for p in window['members']]
    assert len(set(planned)) == len(planned) == 4
    rows.extend(record(1, ts(day, 21), boss=1) for day in (24, 25, 26))
    later = dispatch.build_dispatch(rows, config(1, 2, 3, 4), ts(27), period, {}, bosses, queues, True)
    assert '1' not in {p['pcrid'] for pair in later['pairs'] for p in pair['members']}
    assert next(w for w in later['windows'] if w['slot'] == 8)['members'][0]['pcrid'] == '1'


def test_declarations_override_habits_but_not_freshness_or_availability(dispatch, period):
    now = ts(28)
    bosses, queues = battle()
    queues[1]['apply'] = [declared(11, now), declared(22, now, kind='comp', seconds=60)]
    rows = [record(uid, ts(28, 18, minute)) for uid in (1, 2) for minute in (0, 1, 2)]
    links = {'11': '1', '22': '2'}
    data = dispatch.build_dispatch(rows, config(1, 2), now, period, links, bosses, queues, True)
    assert len(data['pairs']) == 1 and data['pairs'][0]['declared']
    assert data['pairs'][0]['gap'] == -5000000 and all(p['remaining'] == 0 for p in data['pending'])
    assert len(data['windows'][0]['members']) == 2
    stale = dispatch.build_dispatch(rows, config(1, 2), now, period, links, bosses, queues, False)
    assert not stale['pairs']
    bosses[0]['fighter_num'] = 2
    busy = dispatch.build_dispatch(rows, config(1, 2), now, period, links, bosses, queues, True)
    assert busy['pairs'][0]['gap'] is None and '先协调' in busy['pairs'][0]['status']


@pytest.mark.parametrize('blocked', ['tree', 'multiple', 'reservation_conflict'])
def test_linked_pending_state_blocks_pairs_without_matching_duplicate_names(dispatch, period, blocked):
    now = ts(26)
    rows = [record(uid, ts(day)) for uid in (1, 2) for day in (24, 25)]
    bosses, queues = battle()
    if blocked == 'tree':
        queues[1]['tree'] = [(11, now - 10, '')]
    elif blocked == 'multiple':
        queues[1]['apply'] = [declared(11, now)]
        queues[2]['apply'] = [declared(11, now)]
    else:
        queues[1]['apply'] = [declared(11, now)]
        queues[2]['subscribe'] = [(11, 30, '')]
    data = dispatch.build_dispatch(rows, config(1, 2), now, period, {'11': '1', '22': '2'}, bosses, queues, True)
    assert not data['pairs']
    assert data['unplanned'][0]['pcrid'] == '1' and data['unplanned'][0]['blocked']
    assert next(p for p in data['members'] if p['pcrid'] == '2')['blocked'] == ''


def test_member_links_keep_identity_unique_and_ignore_departed_or_ambiguous_links(dispatch):
    roster = {'1': '同名', '2': '同名'}
    assert dispatch.valid_member_links({'11': '1', '22': '1', '33': '99', 'bad': '2'}, roster) == {}
    links = {'11': '1'}
    assert dispatch.register_member_link(links, roster, 22, '2') == {'11': '1', '22': '2'}
    assert links == {'11': '1'}
    for qq, uid in [(11, '2'), (22, '1'), (22, '99')]:
        with pytest.raises(ValueError):
            dispatch.register_member_link(links, roster, qq, uid)
