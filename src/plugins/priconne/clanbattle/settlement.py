"""实际扣血与每日刀型默认配对；推断结果不覆盖原始战绩。"""

from collections import Counter, defaultdict
from datetime import datetime, timedelta
from functools import lru_cache

from .period import GAME_TZ
from .pcr_calculator import solve_equation


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
            record.update(effective_damage=amount, killed=killed,
                          hp_before=amount if killed else None)
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
        if record["effective_damage"] is not None and (record["effective_damage"] != amount or record["killed"] != killed):
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
        event = facts(record).get("event_id")
        bosses[event, record["lap"], str(record["boss"])].append(record)
        day = (datetime.fromtimestamp(record["time"], GAME_TZ) - timedelta(hours=5)).date()
        days[event, str(record["pcrid"]), day].append(record)
    for rows in bosses.values():
        _effective_damage(rows)
    for rows in days.values():
        stock, ordinary, uncertain = [], 0, not _ordered(rows)
        for record in sorted(rows, key=_order):
            manual = facts(record).get("manual_flag")
            seconds, used = record.get("remain_time"), record.get("battle_time")
            killed = record["killed"]
            if type(manual) in (int, float) and manual in (0, .5, 1):
                flag, status = manual, "manual"
            elif type(seconds) is not int or not 1 <= seconds <= 90:
                flag, status = None, "pending"
            elif seconds < 90:
                flag, status = .5, "observed"
            elif killed is True:
                # shortcut: 默认90秒击杀均来自普通挑战，取得明确补偿来源后再替换此假设。
                flag, status = 1, "assumed"
            elif killed is False and not uncertain:
                flag, status = (.5 if any(item[0] == 90 for item in stock) else 0), "assumed"
            else:
                flag, status = None, "pending"
            record.update(flag=flag, kind_status=status)
            if flag is None:
                record["kind_issue"] = "刀型待核验"
                uncertain = True
            elif flag == .5:
                match = next((item for item in stock if item[0] == seconds), None)
                if match is not None and not uncertain:
                    stock.remove(match)
                    record["carry_source"] = match[1]
                else:
                    record["kind_issue"] = "补偿来源待核验"
                    uncertain = True
                record["extended_seconds"] = 0
            else:
                ordinary += 1
                if flag == 0:
                    record["extended_seconds"] = 0
                elif record["hp_before"] and type(used) is int and 0 <= used <= 90 and record["damage"] > 0:
                    extension = _extension(record["hp_before"], record["damage"], used)
                    record["extended_seconds"] = extension
                    stock.append((extension, record.get("battle_log_id")))
                else:
                    record["kind_issue"] = "延长时间待核验"
                    uncertain = True
        if ordinary > 3 or sum(row["flag"] == .5 for row in rows) > 3:
            for record in rows:
                record["kind_issue"] = "每日挑战额度冲突，待核验"
                if record["kind_status"] == "assumed":
                    record.update(flag=None, kind_status="pending", extended_seconds=None, carry_source=None)
    return result


def knife_weight(record):
    return 1 if record.get("flag") == 0 else .5 if record.get("flag") in (.5, 1) else 0


def uncertain(record):
    return record.get("flag") not in (0, .5, 1) or bool(record.get("kind_issue"))


def battle_notice(history, record=None):
    target = f"{history['name']}对{history['lap_num']}周目{history['order_num']}王"
    if not history["kill"]:
        return f"{target}造成了{record['damage'] if record else history['damage']}点伤害。"
    amount = record.get("effective_damage") if record else history.get("damage")
    damage = f"{amount}点伤害" if amount is not None else "伤害待核验"
    raw = str(record["damage"]) if record else "待核验"
    seconds = record.get("extended_seconds") if record else None
    extension = (f"获得延长战斗时间{seconds}s。" if seconds else "") if seconds is not None else "延长战斗时间待核验。"
    return f"{target}造成{damage}并击破（原始伤害{raw}）。{extension}"
