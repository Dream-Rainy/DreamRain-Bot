"""本期档线查询与缓存；共享档线不携带其他群的本会信息。"""

import asyncio
import os
import time

from ..util.tools import load_config, write_config

DEFAULT_RANKS = (1, 2, 3, 10, 20, 50, 200, 600, 1200, 2800, 5000)
_rank_lock = asyncio.Lock()


def parse_ranks(text):
    words = text.replace("，", " ").replace(",", " ").split()
    if not words:
        return DEFAULT_RANKS
    if len(words) > 20 or any(not word.isascii() or not word.isdigit() for word in words):
        raise ValueError("示例：查档线 50 200 600；最多20个名次，范围1～60000。")
    ranks = tuple(sorted({int(word) for word in words}))
    if not ranks or ranks[0] < 1 or ranks[-1] > 60000:
        raise ValueError("名次范围为1～60000。")
    return ranks


def valid_rank(value):
    return type(value) is int and value > 0


def final_rankline_due(period, now):
    return period.end - 300 <= now < period.end


async def save_json(path, data):
    await write_config(path + ".tmp", data)
    os.replace(path + ".tmp", path)


def live_monitors(monitors, period, now):
    return {gid: clan for gid, clan in monitors.items()
            if getattr(clan, "event", None) == period and getattr(clan, "client", None)
            and type(getattr(clan, "loop_check", None)) in (int, float)
            and 0 <= now - clan.loop_check <= 120}


def _ranking(item):
    if not isinstance(item, dict) or not valid_rank(item.get("rank")):
        return None
    damage = item.get("damage")
    if type(damage) is not int or damage < 0:
        return None
    return {"rank": item["rank"], "damage": damage, "clan_name": str(item.get("clan_name") or "—")}


async def _page(clan, period, page, mine=False):
    result = await clan.client.callapi("/clan_battle/period_ranking", {
        "clan_id": clan.clan_id, "clan_battle_id": period.id, "period": 1,
        "month": 0, "page": page, "is_my_clan": int(mine), "is_first": 1,
    }, noerr=False)
    if not isinstance(result, dict) or result.get("clan_battle_id", period.id) != period.id:
        raise ValueError("档线期次不匹配。")
    rows = result.get("period_ranking")
    if rows is None and isinstance(result.get("page_info"), dict):
        rows = result["page_info"].get("period_ranking")
    if not isinstance(rows, list):
        raise ValueError("档线接口未返回排名列表。")
    own = _ranking(result.get("my_clan_data"))
    leader = getattr(clan, "clan_leader_id", None)
    if own is None:
        own = next((_ranking(row) for row in rows if isinstance(row, dict) and (
            row.get("clan_id") == clan.clan_id or
            (type(leader) is int and leader > 0 and row.get("leader_viewer_id") == leader))), None)
    parsed = [_ranking(row) for row in rows]
    if any(value is None for value in parsed):
        raise ValueError("排名页含无效记录，未作为空页处理。")
    return parsed, own


async def _last_rank(clan, period, pages, clock):
    requests = 0

    async def page(number):
        nonlocal requests
        if number not in pages:
            if requests >= 32 or not period.active(clock()):
                raise ValueError("末位暂未核验。")
            requests += 1
            rows, _ = await _page(clan, period, number)
            if not period.active(clock()):
                raise ValueError("活动已结束，未保存排名。")
            pages[number] = rows
        rows = pages[number]
        if any(not number * 10 < row["rank"] <= (number + 1) * 10 for row in rows):
            raise ValueError("排名分页不一致，末位暂未核验。")
        return rows

    low = max(number for number, rows in pages.items() if rows)
    high = max(6000, max(pages) + 1)
    while await page(high):
        low, high = high, high * 2
    while low + 1 < high:
        middle = (low + high) // 2
        if await page(middle):
            low = middle
        else:
            high = middle
    return max(await page(low), key=lambda row: row["rank"])


async def get_rank_lines(path, period, ranks, monitors, group_id, *, clock=None):
    clock = clock or time.time
    async with _rank_lock:
        now = int(clock())
        cache = await load_config(path) or {}
        if not isinstance(cache, dict) or cache.get("period_id") != period.id:
            cache = {"period_id": period.id, "queries": {}, "mine": {}}
        key = ",".join(map(str, ranks))
        cached = cache.get("queries", {}).get(key)
        if not (isinstance(cached, dict) and type(cached.get("updated_at")) is int
                and period.start <= cached["updated_at"] <= min(now, period.end - 1)
                and isinstance(cached.get("lines"), list)):
            cached = None
        live = live_monitors(monitors, period, now) if period.active(now) else {}
        source_id = group_id if group_id in live else next(iter(live), None)
        source = live.get(source_id)
        fresh = cached is not None and cached["updated_at"] // 1800 == now // 1800
        stale = not fresh or not period.active(now)
        my = None
        if source is not None and not fresh:
            try:
                by_rank, pages = {}, {}
                for page in sorted({(rank - 1) // 10 for rank in ranks}):
                    if not period.active(clock()):
                        raise ValueError("活动已结束，停止查询排名。")
                    rows, own = await _page(source, period, page)
                    pages[page] = rows
                    by_rank.update((row["rank"], row) for row in rows)
                    if own is not None:
                        my = own
                if not by_rank:
                    raise ValueError("暂无有效档线数据。")
                last = None
                if tuple(ranks) == DEFAULT_RANKS:
                    try:
                        last = await _last_rank(source, period, pages, clock)
                    except Exception:
                        pass
                if not period.active(clock()):
                    raise ValueError("活动已结束，未保存零点后返回的排名。")
                cached = {"updated_at": now, "lines": [by_rank.get(rank, {"rank": rank, "damage": None, "clan_name": "—"}) for rank in ranks]}
                if tuple(ranks) == DEFAULT_RANKS:
                    cached["last"] = last
                cache.setdefault("queries", {})[key] = cached
                if my is not None:
                    cache.setdefault("mine", {})[str(source_id)] = {**my, "updated_at": now, "clan_id": source.clan_id}
                await save_json(path, cache)
                stale = False
            except Exception:
                if cached is None:
                    raise ValueError("暂时无法取得档线，且本期没有可用缓存。") from None
                stale = True
        if cached is None:
            raise ValueError("本期暂无档线缓存，请先开启出刀监控后查询。")
        own = cache.get("mine", {}).get(str(group_id))
        if not (group_id in live and isinstance(own, dict) and _ranking(own)
                and own.get("clan_id") == live[group_id].clan_id
                and own.get("updated_at") == cached["updated_at"]):
            own = None
        if group_id in live and own is None and not stale:
            try:
                _, own = await _page(live[group_id], period, 0, mine=True)
                if own is not None and period.active(clock()):
                    own = {**own, "updated_at": cached["updated_at"], "clan_id": live[group_id].clan_id}
                    cache.setdefault("mine", {})[str(group_id)] = own
                    await save_json(path, cache)
                else:
                    own = None
            except Exception:
                own = None
        return {**cached, "period_id": period.id, "stale": stale or not period.active(clock()), "my": own}
