"""会战查询、人员登记及可追溯纠错；QQ和Web共用。"""
import os
import asyncio
import time
from datetime import datetime

from fastapi import HTTPException
from nonebot import logger

from .sql import RecordDao, group_write_lock, data_version, game_day_start
from .reports import status_data, daily_data, snapshot_bosses, carry_inventory_members, carry_inventory_text
from .review import build_review, member_data, range_data


async def editor_context(group_id):
    from . import get_period, load_config, clan_path
    period = await get_period(now=int(time.time()))
    config = await load_config(os.path.join(clan_path, str(group_id), "clanbattle.json")) or {}
    return period, config


async def _links(group_id):
    from . import load_config, clan_path
    path = os.path.join(clan_path, str(group_id), "member_links.json")
    raw = await load_config(path)
    if not isinstance(raw, dict) and os.path.isfile(path):
        raise HTTPException(503, "身份登记文件无法读取；未覆盖已有登记。")
    return path, raw if isinstance(raw, dict) else {}


def _link_version(period, config, links):
    return data_version([period.id, config.get("clan_battle_id"), config.get("member_by_id", config.get("member")), links])


async def change_member_link(bot, group_id, qq, uid, *, actor, admin, expected=None, period_id=None):
    from . import write_config
    from .dispatch import register_member_link
    from .reports import member_roster
    qq, actor = str(qq), str(actor)
    if qq != actor and not admin:
        raise HTTPException(403, "代他人操作会战成员登记需要群管理员权限。")
    if uid is not None and (not qq.isascii() or not qq.isdecimal() or qq.startswith("0") or len(qq) > 20):
        raise HTTPException(422, "QQ号不正确")
    if uid is not None and qq != actor:
        try:
            member = await bot.get_group_member_info(group_id=group_id, user_id=int(qq), no_cache=True)
            if str(member.get("user_id")) != qq:
                raise ValueError()
        except Exception:
            raise HTTPException(403, "无法核验该QQ属于本群，未变更关联。")
    async with group_write_lock(group_id):
        period, config = await editor_context(group_id)
        path, links = await _links(group_id)
        if period_id is not None and period.id != period_id:
            raise HTTPException(409, "会战期次已变化，请刷新")
        if expected is not None and expected != _link_version(period, config, links):
            raise HTTPException(409, "成员关联或名册已变化，请刷新")
        if uid is None:
            if qq not in links:
                raise HTTPException(409, "该QQ尚未登记会战成员。")
            updated = dict(links)
            updated.pop(qq)
            message = f"已取消QQ {qq}的会战成员登记。"
        else:
            if config.get("clan_battle_id") != period.id:
                raise HTTPException(409, "名册尚未绑定本期，请开启出刀监控刷新。")
            try:
                updated = register_member_link(links, member_roster(config), qq, uid)
            except ValueError as exc:
                raise HTTPException(409, str(exc))
            message = f"已登记QQ {qq} ↔ {member_roster(config)[str(uid)]}（游戏ID {uid}）。\n仅登记身份对应，不需要账号密码。"
        try:
            await write_config(path + ".tmp", updated)
            os.replace(path + ".tmp", path)
        except OSError:
            raise HTTPException(503, "身份登记保存失败，请重试；原登记已保留。")
    logger.info(f"Clanbattle identity: actor={actor}, group={group_id}, qq={qq}, linked={uid is not None}")
    return {"message": message}


async def queue_entries(group_id, period, config, *, now=None):
    from .sql import get_session, select, Apply, Tree, Subscribe
    now = int(time.time()) if now is None else int(now)
    if config.get("clan_battle_id") != period.id or not period.active(now):
        return []
    entries = []
    async with get_session() as session:
        for kind, model in (("apply", Apply), ("tree", Tree), ("subscribe", Subscribe)):
            result = await session.execute(select(model).where(model.group_id == group_id))
            for row in result.scalars():
                if kind != "subscribe" and not period.start <= row.time < min(period.end, now + 1):
                    continue
                data = {col.name: getattr(row, col.name) for col in model.__table__.columns}
                entries.append(dict(id=row.id, kind=kind, qq=str(row.uid), boss=row.boss,
                                    text=row.text, value=row.lap if kind == "subscribe" else row.time,
                                    expected=data_version(data)))
    return entries


async def remove_registration(group_id, period_id, kind, record_id, expected, *, actor):
    from .sql import get_session, select, delete, Apply, Tree, Subscribe
    model = {"apply": Apply, "tree": Tree, "subscribe": Subscribe}.get(kind)
    if model is None:
        raise HTTPException(422, "登记类型不正确")
    async with group_write_lock(group_id):
        period, config = await editor_context(group_id)
        if period.id != period_id or config.get("clan_battle_id") != period.id or not period.active(int(time.time())):
            raise HTTPException(409, "期次或登记状态已变化，请刷新")
        async with get_session() as session:
            result = await session.execute(select(model).where(model.id == record_id, model.group_id == group_id).with_for_update())
            row = result.scalar_one_or_none()
            if row is None:
                raise HTTPException(409, "登记已改变，请刷新")
            data = {col.name: getattr(row, col.name) for col in model.__table__.columns}
            if expected != data_version(data) or (kind != "subscribe" and not period.start <= row.time < min(period.end, int(time.time()) + 1)):
                raise HTTPException(409, "登记已改变，请刷新")
            await session.execute(delete(model).where(model.id == record_id, model.group_id == group_id))
            await session.commit()
    logger.info(f"Clanbattle registration removed: actor={actor}, group={group_id}, kind={kind}, id={record_id}")
    return {"message": "登记已清理"}


async def people_data(group_id):
    async with group_write_lock(group_id):
        period, config = await editor_context(group_id)
        info = freshness(period)
        now = info["as_of"]
        _, links = await _links(group_id)
        entries = await queue_entries(group_id, period, config, now=now)
        raw = await RecordDao(group_id, period).get_settlement_records(period.start, min(period.end, int(now) + 1)) if period.active(now) else []
    return await asyncio.to_thread(_people_snapshot, period, config, links, entries, raw, info)


def _people_snapshot(period, config, links, entries, raw, info):
    from .dispatch import member_link_rows
    from .reports import member_roster, daily_members, _recorded_knife_rows
    from .settlement import analyse_records
    now = info["as_of"]
    roster = member_roster(config) if config.get("clan_battle_id") == period.id else {}
    rows = [row for row in analyse_records(raw) if max(period.start, game_day_start(now)) <= row["time"] < min(period.end, int(now) + 1)]
    counts = {p["pcrid"]: p for p in daily_members(_recorded_knife_rows(rows), roster)}
    inventories = {p["pcrid"]: carry_inventory_text(p["inventory"]) for p in carry_inventory_members(rows, config, int(now), period)} if period.active(now) else {}
    result = member_link_rows(links, roster)
    for member in result:
        stats = counts.get(member["pcrid"], {})
        member.update(knife=stats.get("knife", 0) if period.active(now) else None, pending=stats.get("pending", 0),
                      inventory=list(inventories.get(member["pcrid"], ("—", "当前不在活动期"))),
                      registrations=[entry for entry in entries if entry["qq"] in member["qq"]])
    represented = {qq for row in result for qq in row["qq"]}
    for qq in sorted({e["qq"] for e in entries} - represented):
        result.append(dict(pcrid="—", name="未关联QQ登记", qq=[qq], state="unbound", knife=0, pending=0,
                           inventory=["—", "身份待关联"], registrations=[e for e in entries if e["qq"] == qq]))
    return dict(items=result, period_id=period.id, version=_link_version(period, config, links), freshness=info)


def record_view(row, *, history=False):
    from .settlement import facts, uncertain
    from .period import GAME_TZ
    meta = facts(row)
    value = {key: row.get(key) for key in ("id", "name", "lap", "boss", "battle_log_id", "damage", "effective_damage", "remain_time", "battle_time", "raw_flag", "flag", "kind_status", "kind_issue", "carry_source_id", "carry_source_ids")}
    value.update(pcrid=str(row["pcrid"]), time=row["time"], time_text=datetime.fromtimestamp(row["time"], GAME_TZ).strftime("%m-%d %H:%M:%S"),
                 manual_flag=meta.get("manual_flag"), manual_source=meta.get("manual_source"), pending=uncertain(row),
                 revision=meta.get("correction_revision", 0), day_start=game_day_start(row["time"]))
    if history:
        value["history"] = list(meta.get("correction_history", []))[-20:]
    return value


async def record_rows(group_id):
    period, config = await editor_context(group_id)
    rows = await RecordDao(group_id, period).get_report_records(period.start, min(period.end, int(time.time()) + 1))
    return period, rows


async def record_detail(group_id, record_id):
    from .settlement import _order, _ordered
    period, rows = await record_rows(group_id)
    row = next((r for r in rows if r["id"] == record_id), None)
    if row is None:
        raise HTTPException(404, "未找到本群本期记录")
    options = [record_view(r) for r in rows if str(r["pcrid"]) == str(row["pcrid"])
               and game_day_start(r["time"]) == game_day_start(row["time"])
               and (r["time"] < row["time"] or r["time"] == row["time"] and _ordered([r, row]) and _order(r) < _order(row))]
    return dict(record=record_view(row, history=True), sources=options, period_id=period.id)


async def change_record(group_id, record_id, flag, source, reason, *, actor, expected=None, period_id=None, commit=False):
    from .reports import daily_members, _recorded_knife_rows
    period, config = await editor_context(group_id)
    if period_id != period.id:
        raise HTTPException(409, "会战期次已变化，请刷新")
    try:
        result = await RecordDao(group_id, period).correct_record(record_id, flag, source=source, actor=str(actor),
                    reason=reason, expected=expected, commit=commit)
    except KeyError:
        raise HTTPException(404, "未找到本群本期记录")
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    def day_view(rows):
        rows = [r for r in rows if str(r["pcrid"]) == result["pcrid"] and game_day_start(r["time"]) == result["day_start"]]
        rows.sort(key=lambda r: (r["time"], r["id"]))
        display = daily_members(_recorded_knife_rows(rows), {})
        inventory = rows[-1]["carry_inventory"] if rows else {}
        return dict(records=[record_view(r) for r in rows], knife=display[0]["knife"] if display else 0,
                    inventory=carry_inventory_text(inventory), status=inventory.get("status"), issue=inventory.get("reason"))
    return dict(version=result["version"], before=day_view(result["before"]), after=day_view(result["after"]), saved=result["saved"])


async def push_settings(group_id):
    from . import _load_push_settings, _push_lock
    async with _push_lock:
        profile = (await _load_push_settings()).get(str(group_id), {})
        return {"broadcast": profile.get("broadcast", True), "rankline": profile.get("rankline", False)}


async def update_push_settings(group_id, self_id, changes, *, expected=None, actor=""):
    from . import _load_push_settings, _push_lock, save_json, clan_path
    if not changes or set(changes) - {"broadcast", "rankline"} or any(type(v) is not bool for v in changes.values()):
        raise HTTPException(422, "仅可修改播报与档线订阅开关")
    async with _push_lock:
        settings = await _load_push_settings()
        profile = dict(settings.get(str(group_id), {}))
        current = {"broadcast": profile.get("broadcast", True), "rankline": profile.get("rankline", False)}
        if expected is not None and expected != current:
            raise HTTPException(409, "设置已发生变化，请刷新后重试")
        profile.update(changes)
        profile["self_id"] = str(self_id)
        updated = {**settings, str(group_id): profile}
        await save_json(os.path.join(clan_path, "push_settings.json"), updated)
        settings.clear()
        settings.update(updated)
    logger.info(f"Clanbattle settings: actor={actor}, group={group_id}, before={current}, changes={changes}")
    return {**current, **changes}


async def report_context(group_id, now, period=None):
    from . import run_group, run_path, clanbattle_info, load_config
    info = run_group.get(group_id)
    if not isinstance(info, dict) or not isinstance(info.get("snapshot"), dict):
        saved = await load_config(run_path)
        info = saved.get(str(group_id), {}) if isinstance(saved, dict) else {}
    info = info if isinstance(info, dict) else {}
    snapshot = info.get("snapshot", {})
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    updated = snapshot.get("time", 0)
    if period is not None and (type(updated) not in (int, float) or not period.start <= updated < period.end
                              or snapshot.get("clan_battle_id") not in (None, period.id)):
        return {}, False
    clan = clanbattle_info.get(group_id)
    online = bool((period is None or period.active(now)) and clan and clan.loop_check
                  and type(updated) in (int, float) and 0 <= now - updated <= 120)
    return snapshot, online


def freshness(period):
    """A short read-cache lifetime, clipped at game-day and activity boundaries."""
    from .carryover import game_day_start
    now = time.time()
    boundary = game_day_start(now) + 86400
    if now < period.start:
        boundary = min(boundary, period.start)
    elif now < period.end:
        boundary = min(boundary, period.end)
    return dict(period_id=period.id, game_day=game_day_start(now), as_of=now,
                valid_until=min(now+10, boundary))


async def query_report(bot, group_id, view, now=None):
    from . import _report_queues, _report_member_names, _dispatch_ready, load_config, get_period, clan_path
    now = int(time.time()) if now is None else now
    period = await get_period(now=now)
    config = await load_config(os.path.join(clan_path, str(group_id), "clanbattle.json")) or {}
    bound = config.get("clan_battle_id") == period.id
    if not bound:
        config = {"clan_battle_id": period.id}
    snapshot, online = await report_context(group_id, now, period)
    bosses = snapshot_bosses(snapshot) if view in {"status", "queues"} else None
    needs_records = (view in {"members", "ranges"} or view == "daily" and period.active(now)
                     or view == "carryover" and period.active(now) and bound or view == "status" and bool(bosses))
    records = await RecordDao(group_id, period).get_report_records(period.start, min(period.end, now + 1)) if needs_records and now >= period.start else []
    hint = "" if _dispatch_ready(snapshot, online, now, period) else "数据待核验，仅展示已保存记录。"
    def finish(data):
        if isinstance(data, str):
            data = dict(title="会战报表", metadata="", cards=[], sections=[], note=data)
        return {**data, "freshness": freshness(period)}
    if view == "daily":
        return finish(daily_data(records, config, now, period, hint))
    if view in {"members", "ranges"}:
        data = build_review(records, config, now, period, group_id)
        return finish(member_data(data) if view == "members" else range_data(data))
    if view == "carryover":
        rows = [[m["name"], *carry_inventory_text(m["inventory"])] for m in carry_inventory_members(records, config, now, period)] if period.active(now) and bound else []
        return finish(dict(title="补偿库存", metadata=period.label(now), cards=[], sections=[("", ["成员", "确定库存", "待核验"], rows, [300, 400, 600])], note=hint or "按已结算记录推断"))
    queues, names = await _report_queues(bot, group_id, bosses, subscribers=view == "queues", member_names=False) if online and bound and bosses else ({}, {})
    if view == "queues":
        from .reports import declaration_text
        queues = {order: {kind: [entry for entry in entries if kind == "subscribe" or period.start <= entry[1] < min(period.end, now + 1)]
                          for kind, entries in queue.items()} for order, queue in queues.items()}
        names = await _report_member_names(bot, group_id, queues)
        rows = []
        for boss, queue in queues.items():
            for kind, entries in queue.items():
                for uid, value, text in entries:
                    rows.append([f"{boss}王", {"apply":"申请", "tree":"挂树", "subscribe":"预约"}[kind], names.get(uid, str(uid)),
                                 f"{value}周目" if kind == "subscribe" else str(max(0, now-value)//60)+"分钟", declaration_text(text)])
        return finish(dict(title="登记队列", metadata=period.label(now), cards=[], sections=[("", ["目标", "类型", "成员", "周目/时长", "留言"], rows, [100,100,250,200,600])], note=hint))
    if view != "status":
        raise HTTPException(404, "报表不存在")
    return finish(status_data(snapshot, online, now, period, group_id, queues, names, records=records))
