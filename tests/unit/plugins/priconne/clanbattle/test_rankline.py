from types import SimpleNamespace

import pytest


@pytest.fixture()
def ranking(app, monkeypatch, tmp_path):
    from src.plugins.priconne import clanbattle as cb
    from src.plugins.priconne.clanbattle import rankline
    from src.plugins.priconne.clanbattle.period import BattlePeriod
    monkeypatch.setattr(cb, "clan_path", str(tmp_path))
    monkeypatch.setattr(cb, "_push_settings", None)
    monkeypatch.setattr(cb, "run_group", {})
    monkeypatch.setattr(cb, "clanbattle_info", {})
    return cb, rankline, BattlePeriod(42, 100, 3600)


def test_zero_missing_and_late_rank_cannot_replace_last_valid_snapshot(ranking, monkeypatch):
    cb, _, period = ranking
    from src.plugins.priconne.clanbattle.model import ClanBattle
    clan = ClanBattle(1)
    clan.event = period
    assert clan.update_rank(200, 3599.5)
    for value in (0, None, -1, True, "100"):
        assert not clan.update_rank(value, 3599.8)
    assert not clan.update_rank(1, 3600)
    assert (clan.rank, clan.rank_at) == (200, 3599)
    cb.run_group[1] = {"qq_id": 7}
    snapshot = dict(time=3599, rank=200, rank_at=3599, clan_battle_id=42,
                    battle_start=100, battle_end=3599, boss="")
    monkeypatch.setattr(cb.time, "time", lambda: 3599.9)
    cb._set_monitor_snapshot(1, snapshot)
    monkeypatch.setattr(cb.time, "time", lambda: 3600)
    cb._set_monitor_snapshot(1, {**snapshot, "rank": 1, "rank_at": 3599})
    assert cb.run_group[1]["snapshot"]["rank"] == 200
    assert cb.run_group[1]["snapshot"]["rank_at"] == 3599
    cb._set_monitor_snapshot(1, {**snapshot, "rank": 0, "clan_battle_id": 43})
    assert cb.run_group[1]["snapshot"]["rank"] is None


async def test_cache_deduplicates_pages_accepts_legacy_shape_and_never_shares_my_clan(ranking, tmp_path):
    _, service, period = ranking
    calls = []
    async def api(path, params, **kwargs):
        calls.append(params)
        assert kwargs == {"noerr": False} and params["is_first"] == 1
        return {"clan_battle_id": 42, "page_info": {"period_ranking": [
            {"rank": 1, "damage": 500, "clan_name": "榜首"},
            {"rank": 2, "damage": 400, "clan_name": "第二"}]},
            "my_clan_data": {"rank": 7, "damage": 200, "clan_name": "我的公会"}}
    clan = SimpleNamespace(event=period, loop_check=1000, client=SimpleNamespace(callapi=api), clan_id=8)
    path = str(tmp_path / "rank.json")
    first = await service.get_rank_lines(path, period, (1, 2, 3), {1: clan}, 1, clock=lambda: 1000)
    other = await service.get_rank_lines(path, period, (1, 2, 3), {}, 2, clock=lambda: 1001)
    assert len(calls) == 1 and calls[0]["page"] == 0
    assert first["my"]["damage"] == 200 and other["my"] is None
    assert first["lines"][2]["damage"] is None
    assert first["updated_at"] == other["updated_at"] == 1000
    assert service.parse_ranks("600，200 200") == (200, 600)
    for bad in ("0", "60001", "-1", "200 xx", "[CQ:at,qq=all]"):
        with pytest.raises(ValueError):
            service.parse_ranks(bad)


async def test_invalid_ranks_and_midnight_do_not_overwrite_cache(ranking, tmp_path):
    _, service, period = ranking
    now, calls, cross = [1000], [], [False]
    async def api(path, params, **kwargs):
        calls.append(params)
        if cross[0]:
            now[0] = period.end
        return {"period_ranking": [{"rank": 1 if len(calls) == 1 else 0, "damage": 500}]}
    clan = SimpleNamespace(event=period, loop_check=1000, client=SimpleNamespace(callapi=api), clan_id=8)
    path = str(tmp_path / "rank.json")
    await service.get_rank_lines(path, period, (1,), {1: clan}, 2, clock=lambda: now[0])
    before = (tmp_path / "rank.json").read_bytes()
    now[0] = clan.loop_check = 1900
    stale = await service.get_rank_lines(path, period, (1,), {1: clan}, 2, clock=lambda: now[0])
    assert stale["stale"] and stale["lines"][0]["damage"] == 500
    assert (tmp_path / "rank.json").read_bytes() == before
    cross[0] = True
    now[0] = clan.loop_check = 3599
    late = await service.get_rank_lines(path, period, (1,), {1: clan}, 2, clock=lambda: now[0])
    assert late["stale"] and (tmp_path / "rank.json").read_bytes() == before
    count = len(calls)
    ended = await service.get_rank_lines(path, period, (1,), {1: clan}, 2, clock=lambda: period.end)
    assert ended["stale"] and len(calls) == count
    with pytest.raises(ValueError):
        await service.get_rank_lines(path, SimpleNamespace(id=43, start=4000, end=5000, active=lambda n: False),
                                     (1,), {}, 2, clock=lambda: 4100)


async def test_slow_valid_response_crossing_midnight_is_not_saved(ranking, tmp_path):
    _, service, period = ranking
    now = [3599]
    async def api(*args, **kwargs):
        now[0] = 3600
        return {"period_ranking": [{"rank": 1, "damage": 500}]}
    clan = SimpleNamespace(event=period, loop_check=3599, client=SimpleNamespace(callapi=api), clan_id=8)
    path = tmp_path / "rank.json"
    with pytest.raises(ValueError):
        await service.get_rank_lines(str(path), period, (1,), {1: clan}, 2, clock=lambda: now[0])
    assert not path.exists()


async def test_muted_broadcast_discards_ordinary_messages_but_keeps_direct_notifications(ranking, monkeypatch):
    cb, _, _ = ranking
    cb._push_settings = {"1": {"broadcast": False}}
    sent = []
    async def send(bot, event, gid, text):
        sent.append(text)
    monkeypatch.setattr(cb, "_loop_send", send)
    await cb._monitor_broadcast(None, None, 1, "旧伤害")
    await cb._loop_send(None, None, 1, "预约通知")
    await cb._loop_send(None, None, 1, "监控已关闭")
    cb._push_settings["1"]["broadcast"] = True
    await cb._monitor_broadcast(None, None, 1, "新伤害")
    assert sent == ["预约通知", "监控已关闭", "新伤害"]


async def test_final_push_unions_subscribers_and_monitors_retries_failure_and_survives_reload(ranking, monkeypatch):
    cb, _, period = ranking
    from src.plugins.permission_admin import core
    cb._push_settings = {"1": {"rankline": True, "self_id": "10", "broadcast": False},
                         "2": {"rankline": True, "self_id": "10"},
                         "3": {"rankline": True, "self_id": "10"}}
    cb.run_group.update({1: {"qq_id": 7, "self_id": "10"}, 4: {"qq_id": 8, "self_id": "10"}})
    sent, fail, now = [], [True], [period.end - 301]
    async def schedule(**kwargs):
        return period
    async def data(*args):
        return {"period_id": 42}
    async def send(bot, gid, message):
        if gid == 2 and fail[0]:
            raise RuntimeError("temporary send failure")
        sent.append(gid)
    monkeypatch.setattr(cb, "get_period", schedule)
    monkeypatch.setattr(cb.time, "time", lambda: now[0])
    monkeypatch.setattr(cb, "get_rank_lines", data)
    monkeypatch.setattr(cb, "rankline_report", lambda *args: "图片")
    monkeypatch.setattr(cb, "get_bot", lambda *args: object())
    monkeypatch.setattr(cb, "send_group", send)
    monkeypatch.setattr(core, "get_permission_manager", lambda: SimpleNamespace(get_snapshot=lambda key: {"blocked_groups": [3]}))
    await cb.final_rankline_broadcast()
    assert sent == []
    now[0] = period.end - 300
    await cb.final_rankline_broadcast()
    assert set(sent) == {1, 4} and len(sent) == 2
    cb._push_settings = None
    fail[0] = False
    await cb.final_rankline_broadcast()
    assert sent.count(1) == sent.count(2) == sent.count(4) == 1
    now[0] = period.end
    await cb.final_rankline_broadcast()
    assert len(sent) == 3


async def test_my_clan_is_matched_by_identity_instead_of_possibly_stale_rank(ranking):
    _, service, period = ranking
    async def api(*args, **kwargs):
        return {"period_ranking": [
            {"rank": 200, "damage": 500, "clan_name": "同名公会", "leader_viewer_id": 111},
            {"rank": 201, "damage": 400, "clan_name": "同名公会", "leader_viewer_id": 222}]}
    clan = SimpleNamespace(client=SimpleNamespace(callapi=api), clan_id=8, rank=200, clan_leader_id=222)
    _, own = await service._page(clan, period, 0, mine=True)
    assert own["rank"] == 201 and own["damage"] == 400
    clan.clan_leader_id = None
    _, own = await service._page(clan, period, 0, mine=True)
    assert own is None


async def test_rebinding_group_to_another_clan_does_not_reuse_own_score(ranking, tmp_path):
    _, service, period = ranking
    async def old_api(*args, **kwargs):
        return {"period_ranking": [{"rank": 1, "damage": 500}],
                "my_clan_data": {"rank": 5, "damage": 100}}
    clan = SimpleNamespace(event=period, loop_check=1000, client=SimpleNamespace(callapi=old_api), clan_id=8)
    path = str(tmp_path / "rank.json")
    first = await service.get_rank_lines(path, period, (1,), {1: clan}, 1, clock=lambda: 1000)
    assert first["my"]["damage"] == 100
    async def unavailable(*args, **kwargs):
        raise RuntimeError("new clan score unavailable")
    clan.clan_id, clan.client = 9, SimpleNamespace(callapi=unavailable)
    result = await service.get_rank_lines(path, period, (1,), {1: clan}, 1, clock=lambda: 1001)
    assert result["my"] is None and result["lines"][0]["damage"] == 500


@pytest.mark.parametrize("total", [4999, 5000, 12347, 60013])
async def test_default_table_finds_actual_last_rank_beyond_requested_nodes(ranking, tmp_path, total):
    _, service, period = ranking
    calls = []
    async def api(path, params, **kwargs):
        page = params["page"]
        calls.append(page)
        return {"period_ranking": [
            {"rank": rank, "damage": total * 1000 - rank, "clan_name": f"公会{rank}"}
            for rank in range(page * 10 + 1, min(total, (page + 1) * 10) + 1)],
            "my_clan_data": {"rank": 220, "damage": total * 1000 - 220, "clan_name": "本会"}}
    clan = SimpleNamespace(event=period, loop_check=1000, client=SimpleNamespace(callapi=api), clan_id=8)
    path = str(tmp_path / "rank.json")
    data = await service.get_rank_lines(path, period, service.parse_ranks(""), {1: clan}, 1, clock=lambda: 1000)
    assert [row["rank"] for row in data["lines"]] == [1, 2, 3, 10, 20, 50, 200, 600, 1200, 2800, 5000]
    assert data["last"]["rank"] == total and data["my"]["rank"] == 220
    assert len(calls) == len(set(calls)) and len(calls) <= 40
    count = len(calls)
    cached = await service.get_rank_lines(path, period, service.parse_ranks(""), {1: clan}, 1, clock=lambda: 1001)
    assert cached["last"] == data["last"] and len(calls) == count


async def test_malformed_end_page_is_not_treated_as_actual_end(ranking, tmp_path):
    _, service, period = ranking
    async def api(path, params, **kwargs):
        if params["page"] == 6000:
            return {"period_ranking": [{"rank": 0, "damage": 0}]}
        return {"period_ranking": [{"rank": params["page"] * 10 + 1, "damage": 500}],
                "my_clan_data": {"rank": 220, "damage": 200}}
    clan = SimpleNamespace(event=period, loop_check=1000, client=SimpleNamespace(callapi=api), clan_id=8)
    result = await service.get_rank_lines(str(tmp_path / "rank.json"), period, service.DEFAULT_RANKS,
                                          {1: clan}, 1, clock=lambda: 1000)
    assert result["last"] is None and result["my"]["rank"] == 220
    assert result["lines"][0]["rank"] == 1 and not result["stale"]
