"""Clan battle management adapter; all group privileges are checked on the bot."""
from fastapi import HTTPException
from nonebot import get_bot, require
from time import perf_counter

require("src.plugins.management")
from src.plugins.management import portal
from src.plugins.management.portal import Module, context_allowed, request_scope
from .service import query_report, push_settings, update_push_settings, freshness
from .service import people_data, change_member_link, remove_registration, record_rows, record_view, record_detail, change_record


async def group_access(member, group_id, *, write=False):
    if member.adapter != "onebot" or not group_id or not context_allowed("priconne", member, group_id):
        raise HTTPException(403, "没有该群的会战访问权限")
    scope = request_scope.get()
    if scope is not None and not scope["active"]:
        scope = None
    key = (member.key, member.bot_id, group_id)
    proof = scope["groups"].get(key) if scope is not None else None
    started = perf_counter()
    try:
        if proof is not None:
            bot, admin = proof
            if write and not admin:
                raise HTTPException(403, "仅群管理员可修改设置")
            return proof
        bot = get_bot(member.bot_id)
        # Check the bot's membership even for superusers; never trust a supplied group id.
        if scope is not None:
            scope["auth_calls"] += 1
        await bot.get_group_member_info(group_id=group_id, user_id=int(bot.self_id), no_cache=True)
        if portal.sessions.admin(member):
            if scope is not None:
                scope["groups"][key] = (bot, True)
            return bot, True
        if scope is not None:
            scope["auth_calls"] += 1
        role = await bot.get_group_member_info(group_id=group_id, user_id=int(member.platform_id), no_cache=True)
        if str(role.get("user_id")) != member.platform_id:
            raise ValueError("Unknown group member")
        admin = role.get("role") in {"owner", "admin"}
        if scope is not None:
            scope["groups"][key] = (bot, admin)
        if write and not admin:
            raise HTTPException(403, "仅群管理员可修改设置")
        return bot, admin
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(403, "无法核验群成员身份，请稍后重试")
    finally:
        if scope is not None:
            scope["auth_seconds"] += perf_counter()-started


async def authorize(member):
    if member.adapter != "onebot":
        return False
    if member.group_id is None:
        return True
    try:
        await group_access(member, member.group_id)
        return True
    except HTTPException:
        return False


def wire_data(value):
    """Preserve ids and raw damage integers beyond JavaScript's exact integer range."""
    if type(value) is int and abs(value) > 2**53-1:
        return str(value)
    if isinstance(value, dict):
        return {str(k): wire_data(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [wire_data(v) for v in value]
    return value


async def dispatch(member, method, path, query, body):
    parts = path.split("/")
    record_route = (len(parts) in (2, 3) and parts[0] == "records" and parts[1].isascii() and parts[1].isdigit()
                    and (len(parts) == 2 or parts[2] in {"preview", "save"}))
    if path not in {"status", "daily", "members", "ranges", "queues", "carryover", "settings", "people", "people/link", "queues/delete", "records"} and not record_route:
        raise HTTPException(404, "接口不存在")
    if set(query) - {"group", "offset", "limit", "q", "state", "pcrid", "day", "boss", "kind"}:
        raise HTTPException(422, "查询参数不正确")
    raw = query.get("group", str(member.group_id or ""))
    if not raw.isdecimal() or not 0 < int(raw) < 2**63:
        raise HTTPException(422, "请先选择群号")
    group_id = int(raw)
    if member.group_id is not None and group_id != member.group_id:
        raise HTTPException(403, "该链接仅授权指定群，请重新创建链接")
    write_paths = {"settings", "people/link", "queues/delete"}
    action = parts[2] if record_route and len(parts) == 3 else None
    if (method != "GET" and (method != "POST" or (path not in write_paths and action is None))
            or method == "GET" and (path in {"people/link", "queues/delete"} or action is not None)):
        raise HTTPException(405, "此接口仅支持查询")
    bot, admin = await group_access(member, group_id, write=method == "POST" and path != "people/link")
    offset, limit = int(query.get("offset", 0)), int(query.get("limit", 30))
    if not 0 <= offset <= 10000 or not 1 <= limit <= 50 or len(query.get("q", "")) > 100:
        raise HTTPException(422, "分页或搜索范围不正确")
    if path == "people/link":
        _body(body, {"period_id", "expected", "qq", "uid"})
        if not isinstance(body["qq"], str) or not 1 <= len(body["qq"]) <= 128 or (body["uid"] is not None and (not isinstance(body["uid"], str) or not body["uid"].isascii() or not body["uid"].isdigit())):
            raise HTTPException(422, "身份登记格式不正确")
        return await change_member_link(bot, group_id, body["qq"], body["uid"], actor=member.platform_id,
                    admin=admin, expected=body["expected"], period_id=body["period_id"])
    if path == "queues/delete":
        _body(body, {"period_id", "expected", "kind", "id"})
        if type(body["id"]) is not int or body["id"] <= 0 or body["kind"] not in {"apply", "tree", "subscribe"}:
            raise HTTPException(422, "登记格式不正确")
        return await remove_registration(group_id, body["period_id"], body["kind"], body["id"], body["expected"], actor=member.platform_id)
    if record_route:
        record_id = int(parts[1])
        if action is None:
            return wire_data({**await record_detail(group_id, record_id), "editable": admin})
        fields = {"period_id", "flag", "source_id", "reason"} | ({"expected"} if action == "save" else set())
        _body(body, fields)
        if (body["flag"] not in {"full", "tail", "comp", "auto"} or not isinstance(body["reason"], str)
                or not 1 <= len(body["reason"].strip()) <= 200
                or body["source_id"] is not None and (type(body["source_id"]) is not int or body["source_id"] <= 0)):
            raise HTTPException(422, "请检查刀型、来源与修正原因")
        result = await change_record(group_id, record_id, {"full": 0, "tail": 1, "comp": .5, "auto": None}[body["flag"]],
                    body["source_id"], body["reason"], actor=member.platform_id, expected=body.get("expected"),
                    period_id=body["period_id"], commit=action == "save")
        return wire_data(result)
    if path == "people":
        data = await people_data(group_id)
        needle, state = query.get("q", "").casefold(), query.get("state", "")
        if state not in {"", "unbound", "invalid", "conflict", "pending", "queue"}:
            raise HTTPException(422, "成员状态不正确")
        rows = [row for row in data["items"] if (not needle or needle in " ".join([row["name"], row["pcrid"], *row["qq"]]).casefold())
                and (not state or state == row["state"] or state == "pending" and row["pending"] or state == "queue" and row["registrations"])]
        return wire_data({**data, "items": rows[offset:offset+limit], "total": len(rows), "editable": admin,
                          "actor": member.platform_id, "has_more": len(rows) > offset+limit})
    if path == "records":
        from .sql import game_day_start
        from .settlement import facts, uncertain
        period, rows = await record_rows(group_id)
        day, boss, kind, needle = query.get("day", ""), query.get("boss", ""), query.get("kind", ""), query.get("q", "").casefold()
        if day not in {"", "1", "2", "3", "4", "5"} or boss not in {"", "1", "2", "3", "4", "5"} or kind not in {"", "full", "tail", "comp", "pending", "manual"}:
            raise HTTPException(422, "筛选格式不正确")
        rows = [row for row in rows if (not day or (game_day_start(row["time"]) - period.start)//86400 + 1 == int(day))
                and (not boss or str(row["boss"]) == boss) and (not query.get("pcrid") or str(row["pcrid"]) == query["pcrid"])
                and (not needle or needle in f"{row['name']} {row['pcrid']} {row['id']}".casefold())
                and (not kind or kind == "pending" and uncertain(row) or kind == "manual" and "manual_flag" in facts(row)
                     or kind in {"full", "tail", "comp"} and row["flag"] == {"full":0, "tail":1, "comp":.5}[kind])]
        rows.sort(key=lambda r: (r["time"], r["id"]), reverse=True)
        return wire_data(dict(items=[record_view(r) for r in rows[offset:offset+limit]], total=len(rows),
                         period_id=period.id, editable=admin, has_more=len(rows)>offset+limit, freshness=freshness(period)))
    if path == "settings":
        if method == "POST":
            if set(body or {}) != {"expected", "changes"} or not isinstance(body["expected"], dict) or not isinstance(body["changes"], dict):
                raise HTTPException(422, "设置格式不正确")
            if set(body["expected"]) != {"broadcast", "rankline"} or any(type(v) is not bool for v in body["expected"].values()):
                raise HTTPException(422, "设置格式不正确")
            settings = await update_push_settings(group_id, bot.self_id, body["changes"], expected=body["expected"], actor=member.platform_id)
        else:
            settings = await push_settings(group_id)
        return {"settings": settings, "editable": admin}
    offset, limit = int(query.get("offset", 0)), int(query.get("limit", 30))
    if not 0 <= offset <= 10000 or not 1 <= limit <= 50:
        raise HTTPException(422, "分页范围不正确")
    data = await query_report(bot, group_id, path)
    if isinstance(data, str):
        data = dict(title="会战报表", metadata="", cards=[], sections=[], note=data)
    cache_info = data.pop("freshness", None)
    totals = []
    if "sections" in data:
        sections = []
        for title, columns, rows, widths in data["sections"]:
            # Hints are bounded and should remain visible when paging member rows.
            totals.append(len(rows))
            sections.append([title, columns, rows if title == "提示" else rows[offset:offset+limit], widths])
        data = {**data, "sections": sections}
    if "columns" in data:
        columns = []
        for column in data["columns"]:
            groups = []
            for group in column["groups"]:
                totals.append(len(group["members"]))
                groups.append({**group, "members": group["members"][offset:offset+limit]})
            columns.append({**column, "groups": groups})
        data = {**data, "columns": columns}
    return {"report": wire_data(data), "offset": offset, "limit": limit,
            "has_more": any(total > offset+limit for total in totals), "editable": admin, "freshness": cache_info}


def register():
    portal.register(Module("clanbattle", "公会战", "priconne", dispatch, authorize))


def _body(body, fields):
    if (not isinstance(body, dict) or set(body) != fields or type(body.get("period_id")) is not int or body["period_id"] <= 0
            or "expected" in fields and (not isinstance(body["expected"], str) or len(body["expected"]) != 64)):
        raise HTTPException(422, "提交格式不正确，请刷新重试")
