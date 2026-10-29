"""实际扣血与每日刀型保守推断；推断结果不覆盖原始战绩。"""

from collections import Counter, defaultdict
from datetime import datetime, timedelta
from functools import lru_cache

from .period import GAME_TZ
from .pcr_calculator import solve_equation
from .carryover import analyse_day


@lru_cache(maxsize=4096)
def _extension(hp, damage, used):
    return min(90, solve_equation("x", hp, damage, 90 - used))


def facts(record):
    value = record.get("settlement")
    return value if isinstance(value, dict) else {}


def _order(record):
    return record["time"], facts(record).get("history_id", 0) or 0


def _ordered(records):
    for moment, count in Counter(r["time"] for r in records).items():
        if count > 1:
            ids = [facts(r).get("history_id") for r in records if r["time"] == moment]
            if any(type(value) is not int or value <= 0 for value in ids) or len(set(ids)) != count:
                return False
    return True


def _effective_damage(records):
    history_ids = Counter(facts(record).get("history_id") for record in records)
    for record in records:
        meta, raw = facts(record), record["damage"]
        amount, killed = meta.get("history_damage"), meta.get("killed")
        duplicate = meta.get("history_id") and history_ids[meta["history_id"]] > 1
        if type(amount) is int and 0 <= amount <= raw and type(killed) is bool and not duplicate:
            record["killed"] = killed
            # 击杀历史也可能包含溢出，须经同王累计扣血核验后才可作为血量。
            if not killed:
                record["effective_damage"] = amount
    observations = [facts(r)["report"] for r in records if isinstance(facts(r).get("report"), dict)]
    if not observations or not _ordered(records):
        return
    report = max(observations, key=lambda item: item.get("observed_at", 0))
    maximum, expected = report.get("max_hp"), report.get("totals")
    if type(maximum) is not int or maximum <= 0 or not isinstance(expected, dict):
        return
    if any(type(value) is not int or value < 0 for value in expected.values()):
        return
    remaining, totals, calculated = maximum, Counter(), []
    for record in sorted(records, key=_order):
        raw = record["damage"]
        if type(raw) is not int or raw < 0 or remaining <= 0:
            return
        amount = min(raw, remaining)
        killed = amount == remaining
        if record["killed"] is not None and record["killed"] != killed:
            return
        if record["effective_damage"] is not None and record["effective_damage"] != amount:
            return
        calculated.append((record, remaining, amount, killed))
        totals[str(record["pcrid"])] += amount
        remaining -= amount
    if dict(+totals) != {str(uid): value for uid, value in expected.items() if value}:
        return
    for record, before, amount, killed in calculated:
        record.update(effective_damage=amount, hp_before=before, killed=killed)


def analyse_records(records):
    result, bosses, days, seen = [], defaultdict(list), defaultdict(list), set()
    for original in records:
        record = dict(original)
        key = (str(record["pcrid"]), record.get("battle_log_id"), record["time"], record["lap"], str(record["boss"]))
        if key[1] and key in seen:
            continue
        seen.add(key)
        record.update(raw_flag=record.get("flag"), flag=None, effective_damage=None,
                      hp_before=None, killed=None, extended_seconds=None,
                      carry_source=None, kind_status="pending", kind_issue="")
        result.append(record)
        event = facts(record).get("event_id") or record.get("event_id")
        bosses[event, record["lap"], str(record["boss"])].append(record)
        day = (datetime.fromtimestamp(record["time"], GAME_TZ) - timedelta(hours=5)).date()
        days[event, str(record["pcrid"]), day].append(record)
    for rows in bosses.values():
        _effective_damage(rows)
    for rows in days.values():
        rows.sort(key=_order)
        for record in rows:
            used = record.get("battle_time")
            record["tail_seconds"] = (
                _extension(record["hp_before"], record["damage"], used)
                if record["killed"] is True and record["hp_before"] and type(used) is int and 0 <= used <= 90 and record["damage"] > 0 else None
            )
        day = analyse_day(rows, complete=all(row.get("day_complete") is True for row in rows), ordered=_ordered(rows))
        for record, verdict in zip(rows, day["records"]):
            record.update(verdict, carry_inventory=day["inventory"])
    return result


def knife_weight(record):
    return 1 if record.get("flag") == 0 else .5 if record.get("flag") in (.5, 1) else 0


def uncertain(record):
    return record.get("flag") not in (0, .5, 1) or bool(record.get("kind_issue"))


def battle_notice(history, record=None):
    target = f"{history['name']}对{history['lap_num']}周目{history['order_num']}王"
    if not history["kill"]:
        return f"{target}造成了{record['damage'] if record else history['damage']}点伤害。"
    amount = record.get("effective_damage") if record else None
    damage = f"{amount}点伤害" if amount is not None else "伤害待核验"
    raw = str(record["damage"]) if record else "待核验"
    seconds = record.get("extended_seconds") if record else None
    extension = (f"获得延长战斗时间{seconds}s。" if seconds else "") if seconds is not None else "延长战斗时间待核验。"
    return f"{target}造成{damage}并击破（原始伤害{raw}）。{extension}"
