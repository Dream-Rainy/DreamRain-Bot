"""clanbattle 数据访问 - 基于 nonebot-plugin-orm"""

import os
import asyncio
from collections import defaultdict
from functools import wraps
from hashlib import sha256
import json
from datetime import datetime, timezone, timedelta
from time import perf_counter

from nonebot import logger

from sqlalchemy import select, delete, update, func
from sqlalchemy.dialects.postgresql import insert

from ..orm import get_session
from ..orm.models import SL, Subscribe, Tree, Apply, Record
from ..util.tools import load_config, lap2stage
from .base import clan_path
from .period import get_period
from .settlement import analyse_records, facts, _order, _ordered
from .carryover import coverage_complete, game_day_start

_group_writes = defaultdict(asyncio.Lock)
_correction_workers = asyncio.Semaphore(2)
MANUAL_FIELDS = ("manual_flag", "manual_source", "correction_revision", "correction_history")


def group_write_lock(group_id):
    return _group_writes[group_id]


def locked_group_write(method):
    @wraps(method)
    async def locked(self, *args, **kwargs):
        async with group_write_lock(self.group_id):
            return await method(self, *args, **kwargs)
    return locked


def data_version(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str).encode()).hexdigest()


async def _run_correction(function, *args):
    async with _correction_workers:
        task = asyncio.create_task(asyncio.to_thread(function, *args))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            # Cancelling the waiter cannot stop its thread or free its worker slot.
            while not task.done():
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    continue
                except Exception:
                    break
            if not task.cancelled():
                task.exception()
            raise


def _correction_fingerprint(period, binding, rows):
    observed, selected, seen = [], {}, set()
    for row in rows:
        identity = (str(row["pcrid"]), row.get("battle_log_id"), row["time"], row["lap"], str(row["boss"]))
        duplicate = bool(identity[1]) and identity in seen
        seen.add(identity)
        meta = facts(row)
        report = meta.get("report")
        if isinstance(report, dict):
            normalized = {k: v for k, v in report.items() if k != "observed_at"}
            observed.append(dict(row, settlement={**meta, "report": normalized}))
            key = (meta.get("event_id") or row.get("event_id"), row["lap"], str(row["boss"]))
            stamp = report.get("observed_at", 0)
            if not duplicate and (key not in selected or stamp > selected[key][0]):
                selected[key] = stamp, normalized
        else:
            observed.append(row)
    # A heartbeat is harmless unless it selects a different boss damage report.
    reports = [[*key, value[1]] for key, value in selected.items()]
    return data_version([period.id, period.start, period.end, binding, observed, reports])


def _prepare_correction(period, binding, raw, record_id, flag, source, reason):
    before = analyse_records(raw)
    if not any(r["id"] == record_id for r in before):
        raise ValueError("该记录与其他战绩重复，无法独立纠正，请先核对来源。")
    target = next(r for r in raw if r["id"] == record_id)
    previous = {k: v for k, v in facts(target).items() if k in ("manual_flag", "manual_source")}
    meta = {k: v for k, v in facts(target).items() if k not in ("manual_flag", "manual_source")}
    if flag is not None:
        meta["manual_flag"] = flag
        if source is not None:
            meta["manual_source"] = source
    draft = [dict(row, settlement=meta) if row["id"] == record_id else row for row in raw]
    day_start = game_day_start(target["time"])
    if source is not None:
        origin = next((r for r in raw if r["id"] == source), None)
        if (origin is None or origin["pcrid"] != target["pcrid"] or origin["time"] > target["time"]
                or origin["time"] == target["time"] and (not _ordered([origin, target]) or _order(origin) >= _order(target))
                or game_day_start(origin["time"]) != day_start):
            raise ValueError("来源必须是本成员同一游戏日更早的记录")
    after = analyse_records(draft)
    affected = [r for r in after if r["pcrid"] == target["pcrid"] and game_day_start(r["time"]) == day_start]
    problem = next((r["carry_inventory"]["reason"] for r in affected if r["carry_inventory"]["status"] == "conflict"), None)
    if problem and flag is not None:
        raise ValueError(problem)
    fingerprint = _correction_fingerprint(period, binding, raw)
    effects = [[r.get(key) for key in ("id", "effective_damage", "hp_before", "killed", "flag", "tail_seconds")]
               for r in before]
    version = data_version([fingerprint, effects, record_id, flag, source, reason.strip()])
    result = dict(version=version, before=before, after=after, record_id=record_id,
                  day_start=day_start, pcrid=str(target["pcrid"]), saved=False)
    return result, fingerprint, meta, previous


async def clear_period_registrations(group_id: int) -> None:
    async with get_session() as sess:
        for model in (Subscribe, Tree, Apply):
            await sess.execute(delete(model).where(model.group_id == group_id))
        await sess.commit()


async def clear_group_data(group_id: int) -> None:
    """清空指定群的所有会战数据（肃正协议）"""
    async with get_session() as sess:
        await sess.execute(delete(SL).where(SL.group_id == group_id))
        await sess.execute(delete(Subscribe).where(Subscribe.group_id == group_id))
        await sess.execute(delete(Tree).where(Tree.group_id == group_id))
        await sess.execute(delete(Apply).where(Apply.group_id == group_id))
        await sess.execute(delete(Record).where(Record.group_id == group_id))
        await sess.commit()


async def _read_report_queues(group_id, orders, *, subscribers=False):
    queues = {order: {"apply": [], "subscribe": [], "tree": []} for order in orders}
    if not queues:
        return queues
    sources = [("apply", Apply, Apply.time), ("tree", Tree, Tree.time)]
    if subscribers:
        sources.append(("subscribe", Subscribe, Subscribe.lap))
    async with get_session() as session:
        for kind, model, field in sources:
            query = select(model.boss, model.uid, field, model.text).where(
                model.group_id == group_id, model.boss.in_(queues))
            if kind == "subscribe":
                query = query.where(Subscribe.lap <= 999)
            result = await session.execute(query.order_by(model.id))
            seen = set()
            for row in result:
                entry = tuple(row)
                if entry not in seen:
                    seen.add(entry)
                    order, uid, value, text = entry
                    queues[order][kind].append((uid, value, text))
    return queues


def pcr_date(timeStamp: int):
    now = datetime.fromtimestamp(timeStamp, tz=timezone(timedelta(hours=8)))
    if now.hour < 5:
        now -= timedelta(days=1)
    return now.replace(hour=5, minute=0, second=0, microsecond=0)


class SLDao:
    def __init__(self, group_id: int):
        self.group_id = group_id

    async def add_sl(self, uid: int) -> int:
        """0 记录成功, 1 当天已有SL, 2 其它错误"""
        time_ts = int(pcr_date(datetime.now().timestamp()).timestamp())
        async with get_session() as sess:
            r = await sess.execute(
                select(SL.uid, SL.last_sl).where(
                    SL.group_id == self.group_id, SL.uid == uid
                )
            )
            row = r.fetchone()
            if not row:
                sess.add(SL(group_id=self.group_id, uid=uid, last_sl=time_ts))
                await sess.commit()
                return 0
            last_sl = row[1]
            if last_sl == time_ts:
                return 1
            await sess.execute(
                update(SL).where(
                    SL.group_id == self.group_id, SL.uid == uid
                ).values(last_sl=time_ts)
            )
            await sess.commit()
            return 0

    async def check_sl(self, uid: int) -> int:
        """0 没有SL, 1 有SL, 2 Error"""
        time_ts = int(pcr_date(datetime.now().timestamp()).timestamp())
        async with get_session() as sess:
            r = await sess.execute(
                select(SL.uid, SL.last_sl).where(
                    SL.group_id == self.group_id, SL.uid == uid
                )
            )
            row = r.fetchone()
            if not row:
                return 0
            return 1 if row[1] == time_ts else 0

    async def refresh(self):
        time_ts = int(pcr_date(datetime.now().timestamp()).timestamp())
        async with get_session() as sess:
            await sess.execute(
                delete(SL).where(
                    SL.group_id == self.group_id, SL.last_sl != time_ts
                )
            )
            await sess.commit()


class SubscribeDao:
    def __init__(self, group_id: int):
        self.group_id = group_id

    async def refresh(self):
        await self.clear_subscriber()

    async def get_subscriber(self, boss: int, lap: int | None = None) -> list[tuple[int, int, str]]:
        lap_val = lap if lap else 999
        async with get_session() as sess:
            r = await sess.execute(
                select(Subscribe.uid, Subscribe.lap, Subscribe.text)
                .where(
                    Subscribe.group_id == self.group_id,
                    Subscribe.boss == boss,
                    Subscribe.lap <= lap_val,
                )
                .distinct()
            )
            return [(row[0], row[1], row[2]) for row in r.fetchall()]

    async def clear_subscriber(self, boss: int | None = None, lap: int | None = None) -> int:
        async with get_session() as sess:
            q = delete(Subscribe).where(Subscribe.group_id == self.group_id)
            if boss is not None:
                q = q.where(Subscribe.boss == boss)
            if lap is not None:
                q = q.where(Subscribe.lap <= lap)
            await sess.execute(q)
            await sess.commit()
            return 1

    @locked_group_write
    async def delete_subscriber(self, uid: int, boss: int) -> int:
        async with get_session() as sess:
            await sess.execute(
                delete(Subscribe).where(
                    Subscribe.group_id == self.group_id,
                    Subscribe.boss == boss,
                    Subscribe.uid == uid,
                )
            )
            await sess.commit()
            return 1

    @locked_group_write
    async def add_subscribe(self, uid: int, boss: int, lap: int, text: str) -> int:
        async with get_session() as sess:
            r = await sess.execute(
                select(Subscribe.uid, Subscribe.lap).where(
                    Subscribe.group_id == self.group_id,
                    Subscribe.boss == boss,
                    Subscribe.uid == uid,
                )
            )
            row = r.fetchone()
            if not row:
                sess.add(
                    Subscribe(
                        group_id=self.group_id,
                        uid=uid,
                        boss=boss,
                        lap=lap,
                        text=text,
                    )
                )
            else:
                await sess.execute(
                    update(Subscribe)
                    .where(
                        Subscribe.group_id == self.group_id,
                        Subscribe.boss == boss,
                        Subscribe.uid == uid,
                    )
                    .values(text=text, lap=lap)
                )
            await sess.commit()
            return 1

    async def notify_subscribe(self, boss: int, lap: int, clan_lap: int) -> str:
        if (
            lap - clan_lap >= 2
            or lap2stage(lap) != lap2stage(clan_lap)
            or not (info := await self.get_subscriber(boss, lap))
        ):
            return ""
        await self.clear_subscriber(boss, lap)
        return " ".join([f"[CQ:at,qq={qq}]" for qq, _, _ in info]) + f"\n你们预约的{boss}王出现了"


class TreeDao:
    def __init__(self, group_id: int):
        self.group_id = group_id

    async def refresh(self):
        await self.clear_tree()

    async def get_tree(self, boss: int) -> list[tuple[int, int, str]]:
        async with get_session() as sess:
            r = await sess.execute(
                select(Tree.uid, Tree.time, Tree.text).where(
                    Tree.group_id == self.group_id, Tree.boss == boss
                ).distinct()
            )
            return [(row[0], row[1], row[2]) for row in r.fetchall()]

    async def clear_tree(self, boss: int | None = None) -> int:
        async with get_session() as sess:
            q = delete(Tree).where(Tree.group_id == self.group_id)
            if boss is not None:
                q = q.where(Tree.boss == boss)
            await sess.execute(q)
            await sess.commit()
            return 1

    @locked_group_write
    async def delete_tree(self, uid: int) -> int:
        async with get_session() as sess:
            await sess.execute(
                delete(Tree).where(
                    Tree.group_id == self.group_id, Tree.uid == uid
                )
            )
            await sess.commit()
            return 1

    @locked_group_write
    async def add_tree(self, uid: int, boss: int | str, text: str) -> int:
        boss_int = int(boss) if isinstance(boss, str) else boss
        async with get_session() as sess:
            r = await sess.execute(
                select(Tree.uid).where(
                    Tree.group_id == self.group_id,
                    Tree.boss == boss_int,
                    Tree.uid == uid,
                )
            )
            row = r.fetchone()
            t = int(datetime.now().timestamp())
            if not row:
                sess.add(
                    Tree(
                        group_id=self.group_id,
                        uid=uid,
                        boss=boss_int,
                        time=t,
                        text=text,
                    )
                )
            else:
                await sess.execute(
                    update(Tree)
                    .where(
                        Tree.group_id == self.group_id,
                        Tree.boss == boss_int,
                        Tree.uid == uid,
                    )
                    .values(text=text)
                )
            await sess.commit()
            return 1

    async def notify_tree(self, boss: int) -> str:
        if not (info := await self.get_tree(boss)):
            return ""
        await self.clear_tree(boss)
        return "以下成员将自动下树：\n" + " ".join(
            [f"[CQ:at,qq={qq}]" for qq, _, _ in info]
        )


class ApplyDao:
    def __init__(self, group_id: int):
        self.group_id = group_id

    async def refresh(self):
        await self.clear_apply()

    async def get_apply(self, boss: int) -> list[tuple[int, int, str]]:
        async with get_session() as sess:
            r = await sess.execute(
                select(Apply.uid, Apply.time, Apply.text).where(
                    Apply.group_id == self.group_id, Apply.boss == boss
                ).distinct()
            )
            return [(row[0], row[1], row[2]) for row in r.fetchall()]

    async def clear_apply(self, boss: int | None = None) -> int:
        async with get_session() as sess:
            q = delete(Apply).where(Apply.group_id == self.group_id)
            if boss is not None:
                q = q.where(Apply.boss == boss)
            await sess.execute(q)
            await sess.commit()
            return 1

    @locked_group_write
    async def delete_apply(self, uid: int) -> int:
        async with get_session() as sess:
            await sess.execute(
                delete(Apply).where(
                    Apply.group_id == self.group_id, Apply.uid == uid
                )
            )
            await sess.commit()
            return 1

    @locked_group_write
    async def add_apply(self, uid: int, boss: int | str, text: str) -> int:
        boss_int = int(boss) if isinstance(boss, str) else boss
        async with get_session() as sess:
            r = await sess.execute(
                select(Apply.uid).where(
                    Apply.group_id == self.group_id,
                    Apply.boss == boss_int,
                    Apply.uid == uid,
                )
            )
            row = r.fetchone()
            t = int(datetime.now().timestamp())
            if not row:
                sess.add(
                    Apply(
                        group_id=self.group_id,
                        uid=uid,
                        boss=boss_int,
                        time=t,
                        text=text,
                    )
                )
            else:
                await sess.execute(
                    update(Apply)
                    .where(
                        Apply.group_id == self.group_id,
                        Apply.boss == boss_int,
                        Apply.uid == uid,
                    )
                    .values(text=text, time=t)
                )
            await sess.commit()
            return 1


def _row_to_record(d: tuple) -> Record:
    """兼容40元素旧记录及末尾附采集依据的新记录。"""
    if len(d) not in (40, 41):
        raise ValueError("无效的战绩字段数")
    metadata = d[40] if len(d) == 41 else None
    if metadata is not None and not isinstance(metadata, dict):
        raise ValueError("无效的采集依据")
    (
        pcrid,
        name,
        time_v,
        lap,
        boss,
        damage,
        flag,
        battle_log_id,
        remain_time,
        battle_time,
        u1, u2, u3, u4, u5,
        u1l, u2l, u3l, u4l, u5l,
        u1d, u2d, u3d, u4d, u5d,
        u1r, u2r, u3r, u4r, u5r,
        u1rank, u2rank, u3rank, u4rank, u5rank,
        u1ue, u2ue, u3ue, u4ue, u5ue,
    ) = d[:40]
    return Record(
        settlement=metadata,
        pcrid=pcrid,
        name=str(name),
        time=time_v,
        lap=lap,
        boss=str(boss),
        damage=damage,
        flag=flag,
        battle_log_id=battle_log_id,
        remain_time=remain_time,
        battle_time=battle_time,
        unit1=u1, unit2=u2, unit3=u3, unit4=u4, unit5=u5,
        unit1_level=u1l, unit2_level=u2l, unit3_level=u3l, unit4_level=u4l, unit5_level=u5l,
        unit1_damage=u1d, unit2_damage=u2d, unit3_damage=u3d, unit4_damage=u4d, unit5_damage=u5d,
        unit1_rarity=u1r, unit2_rarity=u2r, unit3_rarity=u3r, unit4_rarity=u4r, unit5_rarity=u5r,
        unit1_rank=u1rank, unit2_rank=u2rank, unit3_rank=u3rank, unit4_rank=u4rank, unit5_rank=u5rank,
        unit1_unique_equip=u1ue, unit2_unique_equip=u2ue, unit3_unique_equip=u3ue,
        unit4_unique_equip=u4ue, unit5_unique_equip=u5ue,
    )


class RecordDao:
    def __init__(self, group_id: int, period=None):
        self.group_id = group_id
        self.period = period

    async def _bounds(self):
        if self.period is None:
            self.period = await get_period()
        return Record.time >= self.period.start, Record.time < self.period.end

    async def get_report_records(self, start_ts: int, end_ts: int):
        # 配对需要查询区间之前的同日尾刀；返回值仍严格限定请求区间。
        context_start = int(pcr_date(start_ts).timestamp())
        if start_ts > 0:
            if self.period is None:
                try:
                    self.period = await get_period()
                except ValueError:
                    pass
            if self.period is not None and self.period.start <= start_ts < self.period.end:
                context_start = self.period.start
        rows = await self.get_settlement_records(context_start, end_ts)
        started = perf_counter()
        analysed = await asyncio.to_thread(analyse_records, rows)
        logger.debug("Clanbattle stage=analysis rows={} seconds={:.4f}", len(rows), perf_counter()-started)
        return [row for row in analysed if start_ts <= row["time"] < end_ts]

    async def get_settlement_records(self, start_ts, end_ts):
        started = perf_counter()
        async with get_session() as sess:
            result = await sess.execute(
                select(
                    Record.id, Record.pcrid, Record.name, Record.time, Record.lap,
                    Record.boss, Record.flag, Record.battle_log_id, Record.damage,
                    Record.remain_time, Record.battle_time, Record.settlement,
                ).where(
                    Record.group_id == self.group_id,
                    Record.time >= start_ts,
                    Record.time < end_ts,
                ).order_by(Record.time, Record.id)
            )
            rows = [dict(row) for row in result.mappings()]
        config = await load_config(os.path.join(clan_path, str(self.group_id), "clanbattle.json")) or {}
        coverage = config.get("record_coverage") if isinstance(config, dict) else None
        for row in rows:
            event_id = facts(row).get("event_id") or (self.period.id if self.period is not None else None)
            row["event_id"] = event_id
            row["day_complete"] = coverage_complete(coverage, event_id, max(self.period.start, game_day_start(row["time"])) if self.period is not None else game_day_start(row["time"]), row["time"])
        logger.debug("Clanbattle stage=sql rows={} seconds={:.4f}", len(rows), perf_counter()-started)
        return rows

    @locked_group_write
    async def save_settlement_facts(self, records):
        async with get_session() as sess:
            for row in records:
                result = await sess.execute(select(Record).where(
                    Record.id == row["id"], Record.group_id == self.group_id,
                    *(await self._bounds()),
                ).with_for_update())
                stored = result.scalar_one_or_none()
                if stored is not None:
                    meta = {k: v for k, v in row["settlement"].items() if k not in MANUAL_FIELDS}
                    for key in MANUAL_FIELDS:
                        if isinstance(stored.settlement, dict) and key in stored.settlement:
                            meta[key] = stored.settlement[key]
                    stored.settlement = meta
                    row["settlement"] = meta
            await sess.commit()

    @locked_group_write
    async def add_record(self, dao_list: list[tuple]):
        if not dao_list:
            return
        async with get_session() as sess:
            for row in dao_list:
                rec = _row_to_record(row)
                rec.group_id = self.group_id
                sess.add(rec)
            await sess.commit()

    async def get_history(self, battle_log_id: int):
        async with get_session() as sess:
            r = await sess.execute(
                select(
                    Record.lap,
                    Record.boss,
                    Record.damage,
                    Record.unit1,
                    Record.unit2,
                    Record.unit3,
                    Record.unit4,
                    Record.unit5,
                    Record.unit1_rarity,
                    Record.unit2_rarity,
                    Record.unit3_rarity,
                    Record.unit4_rarity,
                    Record.unit5_rarity,
                    Record.unit1_rank,
                    Record.unit2_rank,
                    Record.unit3_rank,
                    Record.unit4_rank,
                    Record.unit5_rank,
                    Record.unit1_damage,
                    Record.unit2_damage,
                    Record.unit3_damage,
                    Record.unit4_damage,
                    Record.unit5_damage,
                    Record.unit1_level,
                    Record.unit2_level,
                    Record.unit3_level,
                    Record.unit4_level,
                    Record.unit5_level,
                    Record.unit1_unique_equip,
                    Record.unit2_unique_equip,
                    Record.unit3_unique_equip,
                    Record.unit4_unique_equip,
                    Record.unit5_unique_equip,
                ).where(
                    Record.group_id == self.group_id,
                    *(await self._bounds()),
                    Record.battle_log_id == battle_log_id,
                )
            )
            return r.fetchone()

    async def get_player_records(self, name: str, day: int):
        date = pcr_date(datetime.now().timestamp()) - timedelta(days=day)
        await self._bounds()
        start = self.period.start if day >= 5 else max(self.period.start, date.timestamp())
        end = self.period.end if day >= 5 else min(self.period.end, (date + timedelta(days=1)).timestamp())
        rows = await self.get_report_records(self.period.start, end)
        return [dict(row, history_id=str(row["battle_log_id"])) for row in rows
                if start <= row["time"] < end and row["name"] == name] or None

    async def get_max_dao(self, now=None) -> int:
        await self._bounds()
        return self.period.quota(datetime.now().timestamp() if now is None else now)

    async def get_all_records(self):
        await self._bounds()
        return await self.get_report_records(self.period.start, self.period.end) or None

    async def get_full_knife_median_damage(self, start_ts: int) -> float | None:
        await self._bounds()
        rows = await self.get_report_records(self.period.start, self.period.end)
        damages = sorted(row["damage"] for row in rows if row["time"] >= start_ts and row["flag"] == 0)
        if not damages:
            return None
        mid = len(damages) // 2
        return float(damages[mid]) if len(damages) % 2 else (damages[mid - 1] + damages[mid]) / 2

    async def get_historical_boss_progress(self):
        latest_time = await self.get_latest_time()
        if not latest_time:
            return None
        async with get_session() as sess:
            r = await sess.execute(
                select(Record.lap, Record.boss, func.sum(Record.damage))
                .where(
                    Record.group_id == self.group_id,
                    *(await self._bounds()),
                    Record.time <= latest_time,
                )
                .group_by(Record.lap, Record.boss)
            )
            rows = r.fetchall()
            if not rows:
                return None
            return {
                "latest_time": latest_time,
                "records": [
                    {"lap": row[0], "boss": row[1], "damage": int(row[2] or 0)}
                    for row in rows
                ],
            }

    async def get_latest_records(self, pcrid: int, time_val: int):
        start_day = pcr_date(time_val)
        async with get_session() as sess:
            r = await sess.execute(
                select(Record.flag)
                .where(
                    Record.group_id == self.group_id,
                    *(await self._bounds()),
                    Record.pcrid == pcrid,
                    Record.time >= start_day.timestamp(),
                    Record.time < time_val,
                )
                .order_by(Record.time.desc())
            )
            row = r.fetchone()
            return row[0] if row else 0

    async def get_day_rcords(self, date_ts: int):
        date = pcr_date(date_ts)
        await self._bounds()
        return await self.get_report_records(max(self.period.start, int(date.timestamp())),
                                             min(self.period.end, int((date + timedelta(days=1)).timestamp()))) or None

    async def get_past_damage(self, lap: int, boss: int | str, pcrid: int) -> int:
        boss_str = str(boss)
        async with get_session() as sess:
            r = await sess.execute(
                select(func.sum(Record.damage)).where(
                    Record.group_id == self.group_id,
                    *(await self._bounds()),
                    Record.lap == lap,
                    Record.boss == boss_str,
                    Record.pcrid == pcrid,
                )
            )
            v = r.scalar_one_or_none()
            return int(v) if v is not None else 0

    async def refresh(self):
        # 历史战绩保留供出刀习惯统计；其他查询通过活动边界隔离。
        return

    async def get_latest_time(self) -> int | float:
        async with get_session() as sess:
            r = await sess.execute(
                select(func.max(Record.time)).where(
                    Record.group_id == self.group_id,
                    *(await self._bounds()),
                )
            )
            v = r.scalar_one_or_none()
            return v if v is not None else 0

    async def correct_dao(self, battle_log_id: int, item: float, *, actor="QQ", reason="QQ群指令修正") -> int:
        async with get_session() as sess:
            result = await sess.execute(select(Record.id).where(
                Record.group_id == self.group_id, *(await self._bounds()), Record.battle_log_id == int(battle_log_id)))
            ids = list(result.scalars())
        if not ids:
            return 0
        if len(ids) != 1:
            raise ValueError("出刀编号对应多条记录，请在后台按成员和记录ID核对，未批量修改。")
        preview = await self.correct_record(ids[0], item, actor=actor, reason=reason)
        await self.correct_record(ids[0], item, actor=actor, reason=reason, expected=preview["version"], commit=True)
        return 1

    async def _correction_rows(self, session, *, lock=False):
        await self._bounds()
        config = await load_config(os.path.join(clan_path, str(self.group_id), "clanbattle.json")) or {}
        binding = config.get("clan_battle_id")
        if binding not in (None, self.period.id):
            raise ValueError("会战期次已变化，请刷新")
        query = select(*Record.__table__.columns).where(Record.group_id == self.group_id, *(await self._bounds()))
        query = query.order_by(Record.time, Record.id)
        if lock:
            query = query.with_for_update()
        result = await session.execute(query)
        rows = [dict(row) for row in result.mappings()]
        coverage = config.get("record_coverage")
        for row in rows:
            row["event_id"] = facts(row).get("event_id") or self.period.id
            row["day_complete"] = coverage_complete(coverage, row["event_id"], max(self.period.start, game_day_start(row["time"])), row["time"])
        return rows, binding

    async def correct_record(self, record_id, flag, *, source=None, actor="", reason="", expected=None, commit=False):
        """Compute on a private snapshot; revalidate under write locks before saving."""
        if flag is not None and (type(flag) not in (int, float) or flag not in (0, .5, 1)):
            raise ValueError("无效刀型")
        if source is not None and (type(source) is not int or source <= 0 or flag != .5):
            raise ValueError("仅补偿刀可以指定来源记录ID")
        if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 200:
            raise ValueError("请填写1至200字的修正原因")
        async with group_write_lock(self.group_id):
            async with get_session() as sess:
                raw, binding = await self._correction_rows(sess)
                target = next((r for r in raw if r["id"] == record_id), None)
                if target is None or target["time"] > datetime.now().timestamp() or facts(target).get("event_id") not in (None, self.period.id):
                    raise KeyError("未找到本群本期的记录")
        result, fingerprint, meta, previous = await _run_correction(
            _prepare_correction, self.period, binding, raw, record_id, flag, source, reason)
        if not commit:
            return result
        if not isinstance(expected, str) or expected != result["version"]:
            raise ValueError("采集或人工记录已发生变化，请重新预览")
        async with group_write_lock(self.group_id):
            async with get_session() as sess:
                current_rows, current_binding = await self._correction_rows(sess, lock=True)
                current_fingerprint = await asyncio.to_thread(_correction_fingerprint, self.period, current_binding, current_rows)
                if fingerprint != current_fingerprint:
                    raise ValueError("采集或人工记录已发生变化，请重新预览")
                revision = int(meta.get("correction_revision", 0)) + 1
                history = list(meta.get("correction_history", []))
                current = {k: v for k, v in meta.items() if k in ("manual_flag", "manual_source")}
                history.append(dict(revision=revision, actor=str(actor), time=int(datetime.now().timestamp()),
                                    reason=reason.strip(), before=previous, after=current))
                meta.update(correction_revision=revision, correction_history=history)
                await sess.execute(update(Record).where(Record.id == record_id, Record.group_id == self.group_id,
                                   *(await self._bounds())).values(settlement=meta))
                await sess.commit()
        result["saved"] = True
        return result

    @locked_group_write
    async def bigfun_check(self, records: list) -> None:
        async with get_session() as sess:
            for record in records:
                for member in record:
                    for damage in member["damage_list"]:
                        result = await sess.execute(select(Record).where(
                            Record.group_id == self.group_id, *(await self._bounds()),
                            Record.time == damage["datetime"],
                        ).with_for_update())
                        matches = result.scalars().all()
                        if len(matches) != 1:
                            continue
                        row = matches[0]
                        meta = dict(row.settlement) if isinstance(row.settlement, dict) else {}
                        if "manual_flag" not in meta and "correction_revision" not in meta:
                            meta["manual_flag"] = .5 if damage.get("reimburse") == 1 else damage.get("kill", 0)
                        # 旧工具的扣血只作为结算依据，保留原始 total_damage。
                        meta.update(history_damage=damage["damage"], killed=bool(damage.get("kill")))
                        row.settlement = meta
            await sess.commit()

    async def member_check(self) -> None:
        config = await load_config(
            os.path.join(clan_path, str(self.group_id), "clanbattle.json")
        )
        member_dict = config.get("member", {})
        async with get_session() as sess:
            r = await sess.execute(
                select(func.max(Record.time)).where(
                    Record.group_id == self.group_id,
                    *(await self._bounds()),
                )
            )
            latest_time = r.scalar_one_or_none() or 0
            r2 = await sess.execute(
                select(Record.pcrid, Record.name).where(
                    Record.group_id == self.group_id,
                    *(await self._bounds()),
                    Record.time <= latest_time,
                )
            )
            for row in r2.fetchall():
                pcrid, name = row[0], row[1]
                if name not in member_dict:
                    for nm, vid in member_dict.items():
                        if vid == pcrid:
                            await sess.execute(
                                update(Record)
                                .where(
                                    Record.group_id == self.group_id,
                                    *(await self._bounds()),
                                    Record.pcrid == pcrid,
                                )
                                .values(name=nm)
                            )
                            break
            await sess.commit()
