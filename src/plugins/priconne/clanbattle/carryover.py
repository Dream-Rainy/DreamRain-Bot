"""按整日合法出刀序列求共识；库存是已结算记录的未配对补偿。"""

from datetime import datetime, timedelta

from .period import GAME_TZ


def game_day_start(moment):
    day = datetime.fromtimestamp(moment, GAME_TZ) - timedelta(hours=5)
    return int(day.replace(hour=5, minute=0, second=0, microsecond=0).timestamp())


def coverage_complete(coverage, event_id, day_start, through):
    return bool(isinstance(coverage, dict) and coverage.get("complete") is True
                and coverage.get("event_id") == event_id
                and type(coverage.get("start")) is int and coverage["start"] <= day_start
                and type(coverage.get("through")) is int and coverage["through"] >= through)


def _manual(record):
    meta = record.get("settlement")
    value = meta.get("manual_flag") if isinstance(meta, dict) else None
    return value if type(value) in (int, float) and value in (0, .5, 1) else None


def _units(record):
    meta = record.get("settlement")
    owners = meta.get("unit_owners") if isinstance(meta, dict) else None
    if not isinstance(owners, list) or not 1 <= len(owners) <= 5:
        return frozenset(), None
    own, possible, ids = set(), set(), set()
    for item in owners:
        if not isinstance(item, dict) or type(item.get("unit_id")) is not int or item["unit_id"] <= 0:
            return frozenset(), None
        uid, owner = item["unit_id"], item.get("viewer_id")
        if uid in ids:
            return frozenset(), None
        ids.add(uid)
        if type(owner) is not int or owner <= 0:
            possible.add(uid)
        elif str(owner) == str(record["pcrid"]):
            own.add(uid)
            possible.add(uid)
    return frozenset(own), frozenset(possible)


def _fallback(records, status, reason):
    verdicts = []
    for record in records:
        manual = _manual(record)
        short = type(record.get("remain_time")) is int and 0 < record["remain_time"] < 90
        flag = manual if manual is not None else .5 if short else None
        seconds = record.get("tail_seconds") if flag == 1 else 0 if flag is not None else None
        verdicts.append(dict(flag=flag, kind_status="manual" if manual is not None else "observed" if short else "pending",
                             kind_issue=reason if flag is None or status == "conflict" else "",
                             extended_seconds=seconds, carry_source=None, carry_sources=()))
    return dict(records=verdicts, inventory=dict(status=status, reason=reason, seconds={}, total=None))


def analyse_day(records, *, complete, ordered=True):
    """不丢弃合法分支；无法穷尽时降级，不把未知库存当作零。"""
    records = list(records)
    positions = {r.get("id"): i for i, r in enumerate(records) if r.get("id") is not None}
    claimed = set()
    for index, record in enumerate(records):
        manual = _manual(record)
        if (manual in (0, 1) and type(record.get("remain_time")) is int and 0 < record["remain_time"] < 90
                or manual == 0 and record.get("killed") is True
                or manual == 1 and record.get("killed") is False):
            return _fallback(records, "conflict", "人工刀型与已知时长或击杀事实冲突")
        meta = record.get("settlement")
        source = meta.get("manual_source") if isinstance(meta, dict) else None
        if source is not None and (_manual(record) != .5 or type(source) is not int
                                   or source not in positions or positions[source] >= index):
            return _fallback(records, "conflict", "人工补偿来源不在同成员同日的更早记录中")
        if source is not None:
            origin = records[positions[source]]
            if (source in claimed or str(origin["pcrid"]) != str(record["pcrid"])
                    or origin.get("killed") is False or _manual(origin) in (0, .5)
                    or (type(origin.get("remain_time")) is int and 0 < origin["remain_time"] < 90)
                    or (origin.get("tail_seconds") is not None and type(record.get("remain_time")) is int
                        and 1 <= record["remain_time"] <= 90 and origin["tail_seconds"] != record["remain_time"])
                    or ("time" in record and "time" in origin and game_day_start(record["time"]) != game_day_start(origin["time"]))):
                return _fallback(records, "conflict", "补偿来源重复使用或与已知战斗事实冲突")
            claimed.add(source)
    if sum(_manual(r) in (0, 1) for r in records) > 3:
        return _fallback(records, "conflict", "人工修正后的正常起刀超过每日三次")
    if not ordered:
        return _fallback(records, "order", "出刀顺序待核验")
    if not complete:
        return _fallback(records, "incomplete", "历史覆盖待核验")
    evidence = [_units(record) for record in records]
    # 正常起刀次数、未消耗的(秒数, 来源序号)、逐刀类型、逐刀补偿来源。
    states = {(0, (), (), ())}
    used = frozenset()
    for index, record in enumerate(records):
        start, killed, manual = record.get("remain_time"), record.get("killed"), _manual(record)
        meta = record.get("settlement")
        selected = meta.get("manual_source") if isinstance(meta, dict) else None
        if type(start) is not int or not 1 <= start <= 90:
            return _fallback(records, "incomplete", "起始秒数待核验")
        own, _ = evidence[index]
        reused = own & used
        used |= own
        next_states = set()
        normal_flags = (manual,) if manual in (0, 1) else (1,) if killed is True else (0,) if killed is False else (0, 1)
        for starts, tokens, flags, sources in states:
            if start == 90 and manual != .5 and starts < 3 and not reused:
                for flag in normal_flags:
                    if (flag == 0 and killed is True) or (flag == 1 and killed is False):
                        continue
                    earned = ((record.get("tail_seconds"), index),) if flag == 1 else ()
                    next_states.add((starts + 1, tokens + earned, flags + (flag,), sources + (None,)))
            if manual not in (0, 1):
                for position, (length, origin) in enumerate(tokens):
                    if selected is not None and records[origin].get("id") != selected:
                        continue
                    allowed = evidence[origin][1]
                    if (length is None or length == start) and (allowed is None or reused <= allowed):
                        next_states.add((starts, tokens[:position] + tokens[position + 1:],
                                         flags + (.5,), sources + (origin,)))
        if not next_states:
            return _fallback(records, "conflict", "出刀记录或人工修正冲突")
        if len(next_states) > 2048:
            return _fallback(records, "limit", "合法组合过多，待核验")
        states = next_states
    verdicts = []
    for index, record in enumerate(records):
        kinds = {state[2][index] for state in states}
        flag = next(iter(kinds)) if len(kinds) == 1 else None
        origins = {state[3][index] for state in states}
        source = next(iter(origins)) if len(origins) == 1 else None
        seconds = {record.get("tail_seconds") if state[2][index] == 1 else 0 for state in states}
        extended = next(iter(seconds)) if len(seconds) == 1 else None
        manual = _manual(record)
        verdicts.append(dict(
            flag=flag, kind_status="manual" if manual is not None else "observed" if record["remain_time"] < 90 else "inferred" if flag is not None else "pending",
            kind_issue="刀型待核验" if flag is None else "补偿秒数待核验" if flag == 1 and extended is None else "",
            extended_seconds=extended,
            carry_source=records[source].get("battle_log_id") if source is not None else None,
            carry_source_id=records[source].get("id") if source is not None else None,
            carry_source_ids=tuple(records[i]["id"] for i in sorted(origins - {None}) if records[i].get("id") is not None),
            carry_sources=tuple(sorted({records[i].get("battle_log_id") for i in origins if i is not None and records[i].get("battle_log_id") is not None})),
        ))
    lengths = {length for _, tokens, _, _ in states for length, _ in tokens}
    amounts = {length: (min(sum(token[0] == length for token in state[1]) for state in states),
                        max(sum(token[0] == length for token in state[1]) for state in states)) for length in lengths}
    total = min(len(state[1]) for state in states), max(len(state[1]) for state in states)
    return dict(records=verdicts, inventory=dict(status="ok", reason="", seconds=amounts, total=total))
