"""会长调度报表；所有时间使用游戏日的 UTC+8 口径。"""

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import json
import math
import re
from statistics import median

from ..util.tools import lap2stage
from .base import float2int, format_bignum, format_time
from .render import _report_image
from .sql import pcr_date

GAME_TZ = timezone(timedelta(hours=8))
DECLARATION_PREFIX = "[出刀申报]"


def parse_declaration_input(text):
    if text.startswith(DECLARATION_PREFIX):
        raise ValueError("请使用申请出刀的伤害申报格式。")
    if not re.match(r"^(?:完整(?:\s|$)|补偿(?:[0-9]|\s|$))", text):
        return None
    match = re.fullmatch(r"(完整|补偿([0-9]{1,2})秒)\s+([0-9]{1,10})(?:万|[wW])(?:\s+(.{1,200}))?", text)
    if not match:
        raise ValueError("申报格式：申请出刀 3 完整 1000万 [留言]，或申请出刀 3 补偿60秒 450万 [留言]。")
    seconds = int(match[2]) if match[2] else 90
    damage = int(match[3]) * 10000
    if not 1 <= seconds <= 90 or damage <= 0:
        raise ValueError("伤害须为正整数万，补偿时长须为1–90秒。")
    return {"kind": "comp" if match[2] else "full", "seconds": seconds,
            "damage": damage, "note": match[4] or ""}


def encode_declaration(declaration):
    return DECLARATION_PREFIX + json.dumps(declaration, ensure_ascii=False, separators=(",", ":"))


def decode_declaration(text):
    if not isinstance(text, str) or not text.startswith(DECLARATION_PREFIX):
        return None
    try:
        value = json.loads(text[len(DECLARATION_PREFIX):])
        if not isinstance(value, dict):
            return None
        if any(type(value.get(key)) is not int or value[key] <= 0
               for key in ("event", "lap", "hp", "damage", "seconds")):
            return None
        if value.get("kind") not in ("full", "comp") or not 1 <= value["seconds"] <= 90:
            return None
        if value["kind"] == "full" and value["seconds"] != 90:
            return None
        if not isinstance(value.get("note"), str) or len(value["note"]) > 200:
            return None
        return value
    except (ValueError, TypeError):
        return None


def declaration_text(text):
    declared = decode_declaration(text)
    if declared is None:
        return text.strip() or "无留言"
    kind = "完整90秒" if declared["kind"] == "full" else f"补偿{declared['seconds']}秒"
    return (f"{declared['lap']}周目 {kind} {format_bignum(declared['damage'])}"
            + (f"｜{declared['note']}" if declared["note"] else ""))


def _applicant_name(uid, names):
    name = names.get(uid, f"QQ {uid}")
    return f"{name} (QQ {uid})" if name != f"QQ {uid}" else name


def format_timestamp(value):
    try:
        if not value or isinstance(value, bool) or value <= 0:
            return "未知"
        return datetime.fromtimestamp(value, GAME_TZ).strftime("%m-%d %H:%M:%S")
    except (TypeError, ValueError, OverflowError, OSError):
        return "未知"


def member_roster(config):
    if not isinstance(config, dict):
        return {}
    by_id = config.get("member_by_id")
    if isinstance(by_id, dict):
        return {str(uid): str(name) for uid, name in by_id.items() if str(uid).isdigit()}
    legacy = config.get("member", {})
    if not isinstance(legacy, dict):
        return {}
    return {str(uid): str(name) for name, uid in legacy.items() if str(uid).isdigit()}


def report_status(snapshot, online, now):
    updated = snapshot.get("time", 0)
    synced = snapshot.get("records_synced_at", 0)
    lines = [
        f"监控：{'在线' if online else '离线/状态过期'}｜生成：{format_timestamp(now)}",
        f"游戏状态刷新：{format_timestamp(updated)}",
        f"战绩成功同步：{format_timestamp(synced)}",
    ]
    if snapshot.get("record_sync_ok") is False:
        lines.append("战绩采集异常，数据可能缺失，请核验。")
    elif not online or format_timestamp(synced) == "未知":
        lines.append("战绩同步状态待核验，仅展示已保存的数据。")
    elif now - synced > 120:
        lines.append("战绩已超过2分钟未成功同步，未完成量需核验。")
    return "\n".join(lines)


def boss_snapshot(clan_info, now):
    return [
        {"order": boss.order, "lap_num": boss.lap_num, "stage": boss.stage,
         "current_hp": boss.current_hp, "max_hp": boss.max_hp,
         "available": boss.check_available(clan_info.lap_num, clan_info.period),
         "fighter_num": boss.fighter_num if (
             boss.fighter_lap == boss.lap_num and 0 <= now - boss.fighter_updated_at <= 120
         ) else None}
        for boss in clan_info.boss
    ]


def snapshot_bosses(snapshot):
    bosses = snapshot.get("bosses")
    if not isinstance(bosses, list) or len(bosses) != 5:
        return None
    for boss in bosses:
        if not isinstance(boss, dict):
            return None
        if any(type(boss.get(key)) is not int or boss[key] < 0
               for key in ("order", "lap_num", "current_hp", "max_hp")):
            return None
        if not isinstance(boss.get("stage"), str) or type(boss.get("available")) is not bool:
            return None
        fighters = boss.get("fighter_num")
        if fighters is not None and (type(fighters) is not int or fighters < 0):
            return None
    if {boss["order"] for boss in bosses} != {1, 2, 3, 4, 5}:
        return None
    return sorted(bosses, key=lambda boss: boss["order"])


def status_report(snapshot, online, now, period, group_id, queues=None, names=None, details=False):
    updated = snapshot.get("time", 0)
    if (type(updated) not in (int, float) or not period.start <= updated < period.end
            or snapshot.get("clan_battle_id") not in (None, period.id)):
        snapshot, updated = {}, 0
    live = bool(snapshot and online and period.active(now) and 0 <= now - updated <= 120)
    bosses = snapshot_bosses(snapshot)
    queues = {order: {kind: [row for row in queue[kind] if period.start <= row[1] < min(period.end, now + 1)]
                      for kind in ("apply", "tree")}
              for order, queue in (queues or {}).items()} if live and bosses else {}
    names = names or {}
    applications = declared_applications(bosses or [], queues, now, live, period.id)
    synced = snapshot.get("records_synced_at", 0)
    if type(synced) not in (int, float) or not period.start <= synced <= now:
        synced = 0
    sync_issue = ("采集异常" if snapshot.get("record_sync_ok") is False else
                  "待核验" if not synced or not live else
                  "同步过期" if now - synced > 120 else "正常")
    activity = "未开始" if now < period.start else "已结束" if now >= period.end else f"第{period.days(now)}/5天"
    sections = [("", ["游戏状态刷新", "战绩成功同步"],
                 [[format_timestamp(updated), f"{format_timestamp(synced)} · {sync_issue}"]], [680, 680])]
    if bosses:
        rows = []
        for boss in bosses:
            order = boss["order"]
            queue = queues.get(order)
            applies = applications.get(order, [])
            trees = queue["tree"] if queue is not None else []
            fighters = boss["fighter_num"] if live else None
            hp, maximum = boss["current_hp"], boss["max_hp"]
            available = boss["available"] and hp > 0
            state = "历史快照" if not live else "可挑战" if available else "暂不可挑战"
            issue = any(row["declaration"] is not None and row["issue"] for row in applies)
            if not live:
                hint = "现场待核验"
            elif fighters is not None and fighters >= 2:
                hint = "多人挑战，协调结算"
            elif trees:
                hint = "挂树待确认"
            elif issue:
                hint = "伤害申报需重确认"
            elif applies and fighters == 0 and available:
                hint = "有申请，待安排"
            elif fighters is None:
                hint = "挑战人数待刷新"
            else:
                hint = "登记待确认" if queue is None else "—"
            rows.append([f"{order}王\n{boss['lap_num']}周目 · {boss['stage']}",
                         f"{format_bignum(hp)}/{format_bignum(maximum)}\n{hp/maximum:.1%}" if maximum else "未知",
                         state, fighters if fighters is not None else "未知",
                         len(applies) if queue is not None else "未知", len(trees) if queue is not None else "未知", hint])
        sections.append(("五王进度", ["目标", "剩余HP / 总HP", "状态", "挑战人数", "申请登记", "挂树登记", "待处理"],
                         rows, [200, 300, 160, 110, 110, 110, 370]))
    else:
        sections.append(("已保存进度" if snapshot else "本期进度", ["进度记录"],
                         [[snapshot.get("boss") or "暂无本期状态"]], [1360]))
    if details and queues:
        rows = []
        for boss in bosses:
            order = boss["order"]
            for row in applications[order]:
                label = (row["issue"] or "有效伤害申报") if row["declaration"] else "留言申请"
                elapsed = format_time(max(0, int(now - row["time"]))) or "0秒"
                rows.append([f"{order}王 · 申请", _applicant_name(row["uid"], names), f"已登记{elapsed}",
                             declaration_text(row["text"]) + "\n" + label])
            for uid, registered, text in queues.get(order, {}).get("tree", []):
                elapsed = format_time(max(0, int(now - registered))) or "0秒"
                rows.append([f"{order}王 · 挂树", _applicant_name(uid, names), f"已登记{elapsed}", declaration_text(text)])
        sections.append(("申请与挂树", ["登记", "成员", "时长", "内容 / 状态"],
                         rows or [["—", "暂无申请或挂树登记", "—", "—"]], [160, 300, 220, 680]))
    actions = []
    if now >= period.end:
        actions.append("会战已结束，发送【会战复盘】查看当期总结。")
    elif now < period.start:
        actions.append("活动尚未开始，开战后让监控人发送【出刀监控】。")
    elif not snapshot:
        actions.append("暂无本期状态，让监控人发送【出刀监控】刷新。")
    elif not live:
        issue = "状态已过期" if now - updated > 120 else "监控离线"
        actions.append(f"{issue}，让监控人发送【出刀监控】；先核验现场再排刀。")
    else:
        if sync_issue != "正常":
            actions.append(f"战绩{sync_issue}，请监控人核验；暂不按记录判断剩刀。")
        if not bosses:
            actions.append("旧版快照缺少现场人数与登记，等待监控刷新。")
        else:
            multiple = [str(b['order']) for b in bosses if b['fighter_num'] is not None and b['fighter_num'] >= 2]
            trees = [str(order) for order, queue in queues.items() if queue["tree"]]
            invalid = [str(order) for order, rows in applications.items()
                       if any(row["declaration"] is not None and row["issue"] for row in rows)]
            if multiple:
                actions.append(f"{'、'.join(multiple)}王多人挑战，先协调结算。")
            if trees:
                actions.append(f"{'、'.join(trees)}王有挂树，发送【查树】查看。")
            if invalid:
                actions.append(f"{'、'.join(invalid)}王申报待重确认，查看【boss状态】后重新【申请出刀】。")
        if not actions:
            actions.append("排刀与合刀看【会战指挥台】；成员出刀记录看【今日刀表】。")
    sections.append(("提示", ["当前建议"], [[text] for text in actions[:2]], [1360]))
    start, end = datetime.fromtimestamp(period.start, GAME_TZ), datetime.fromtimestamp(period.end - 1, GAME_TZ)
    rank = snapshot.get("rank")
    monitor = ("在线" if live else "待刷新" if not snapshot else "历史" if not period.active(now) else
               "已过期" if now - updated > 120 else "离线")
    return _report_image("BOSS状态" if details else "会战状态",
                         f"第{period.id}期｜{start:%m-%d}～{end:%m-%d}｜群{group_id}｜{format_timestamp(now)}", [
        (activity, "活动进度"), (f"{rank}名" if type(rank) is int and rank > 0 else "—", "保存排名"),
        (min(b["lap_num"] for b in bosses) if bosses else "—", "最低周目"),
        (monitor, "监控状态")], sections, "")


def registration_report(kind, entries, names, now, period, group_id, snapshot=None, online=False, bound=True):
    subscriptions = kind == "subscribe"
    active = period.active(now)
    entries = entries if active and bound else {}
    snapshot = snapshot or {}
    updated = snapshot.get("time", 0)
    live = (online and active and type(updated) in (int, float)
            and period.start <= updated < period.end and 0 <= now - updated <= 120
            and snapshot.get("clan_battle_id") == period.id)
    bosses = snapshot_bosses(snapshot) if live else None
    laps = {boss["order"]: boss["lap_num"] for boss in bosses or []}
    registrations = [(order, uid, value, text) for order in range(1, 6)
                     for uid, value, text in entries.get(order, [])
                     if subscriptions or period.start <= value <= now and value < period.end]
    registrations.sort(key=lambda row: (row[0], row[2], row[1]) if subscriptions else (row[2], row[0], row[1]))
    rows, expired = [], set()
    for order, uid, value, text in registrations:
        if subscriptions:
            current = laps.get(order)
            target = f"{value}周目" if value else (f"当前 · {current}周目" if current else "当前周目")
            if current is None:
                check = "待核验"
            elif value and value < current:
                check = "已过周目，请重新预约"
                expired.add(order)
            else:
                check = "当前周目" if value in (0, current) else f"后续周目 · 当前{current}"
            rows.append([f"{order}王", _applicant_name(uid, names), target, text.strip() or "—", check])
        else:
            elapsed = format_time(int(now - value)) or "0秒"
            rows.append([f"{order}王", _applicant_name(uid, names),
                         f"{elapsed}\n{format_timestamp(value)}", text.strip() or "—"])
    actions = []
    if now >= period.end:
        empty = "活动已结束"
        actions.append("发送【会战复盘】查看当期总结。")
    elif now < period.start:
        empty = "活动尚未开始"
        actions.append("开战后让监控人发送【出刀监控】。")
    elif not bound:
        empty = "本期登记尚未就绪"
        actions.append("让监控人发送【出刀监控】绑定本期后再登记。")
    else:
        empty = "暂无预约登记" if subscriptions else "暂无挂树登记"
        if subscriptions:
            if not bosses:
                actions.append("周目待核验，让监控人发送【出刀监控】刷新。")
            if expired:
                order = min(expired)
                actions.append(f"已过周目的预约需重约；取消示例【取消预约 {order}】。")
            else:
                actions.append("预约示例【预约 3 42 等下一轮】；取消示例【取消预约 3】。")
        elif rows:
            actions.extend(["完成结算后发送【下树】清除登记。", "合刀安排看【会战指挥台】。"])
        else:
            actions.append("挂树示例【挂树 3 等待协调】；完成后【下树】。")
    columns = ["目标", "成员", "预约周目", "留言", "周目核验"] if subscriptions else ["目标", "成员", "登记时长 / 时间", "留言"]
    widths = [110, 310, 190, 280, 470] if subscriptions else [110, 310, 210, 730]
    if not rows:
        rows = [["—", empty, *["—"] * (len(columns) - 2)]]
    sections = [("预约登记" if subscriptions else "挂树登记 · 从久到近", columns, rows, widths),
                ("提示", ["当前建议"], [[text] for text in actions[:2]], [1360])]
    activity = "未开始" if now < period.start else "已结束" if not active else f"第{period.days(now)}/5天"
    last_value = (("最新" if bosses else "待核验") if active and bound else "—") if subscriptions else (
        (format_time(int(now - registrations[0][2])) or "0秒") if registrations else "—")
    return _report_image("预约表" if subscriptions else "挂树表",
                         f"第{period.id}期｜群{group_id}｜{format_timestamp(now)}", [
        (activity, "活动进度"), (len({row[1] for row in registrations}), "登记成员"),
        (len(registrations), "登记条数"), (last_value, "周目核验" if subscriptions else "最长登记时长")],
        sections, "")


def daily_members(records, roster):
    players = {
        uid: {"pcrid": uid, "name": name, "full": 0, "tail": 0, "comp": 0,
              "knife": 0, "latest": None, "notes": []}
        for uid, name in roster.items()
    }
    for record in records:
        uid = str(record["pcrid"])
        if uid not in players:
            players[uid] = {"pcrid": uid, "name": record["name"], "full": 0,
                            "tail": 0, "comp": 0, "knife": 0, "latest": None,
                            "notes": ["名册外成员"]}
        player = players[uid]
        latest = player["latest"]
        if latest is None or record["time"] >= latest["time"]:
            player["latest"] = record
            if uid not in roster:
                player["name"] = record["name"]
        kind = {0: "full", 1: "tail", 0.5: "comp"}.get(record["flag"])
        if kind is None:
            if "刀型待确认" not in player["notes"]:
                player["notes"].append("刀型待确认")
        else:
            player[kind] += 1
            player["knife"] += 1 if kind == "full" else 0.5
    for player in players.values():
        player["remaining"] = max(0, 3 - player["knife"])
        if player["latest"] is None:
            player["notes"].append("今日无记录，需确认")
        if player["knife"] > 3:
            player["notes"].append("超过3等效，需核验")
    return sorted(players.values(), key=lambda p: (-p["remaining"], p["pcrid"]))


def daily_report(records, config, now, period=None):
    if period is not None and not period.active(now):
        return (period.label(now) + "\n今日刀表｜当前不在出刀活动时间内，今日不产生出刀额度。"
                "\n请查询【当前战报】查看本期累计。")
    roster = member_roster(config)
    players = daily_members(records, roster)
    start = pcr_date(now)
    end_text = f"{start + timedelta(days=1):%m-%d 05:00}"
    if period is not None and period.end < (start + timedelta(days=1)).timestamp():
        end_text = datetime.fromtimestamp(period.end - 1, GAME_TZ).strftime("%m-%d %H:%M:%S")
    rows = []
    for player in players:
        latest = player["latest"]
        last_text = "无记录"
        if latest:
            last_text = (
                f"{format_timestamp(latest['time'])}\n"
                f"{latest['lap']}周目{latest['boss']}王"
            )
        rows.append([
            f"{player['name']}\n{player['pcrid']}",
            f"{player['full']}/{player['tail']}/{player['comp']}",
            float2int(player["knife"]), float2int(player["remaining"]),
            last_text, "；".join(player["notes"]) or "—",
        ])
    achieved = sum(p["knife"] >= 3 for p in players if p["pcrid"] in roster)
    remaining = sum(p["remaining"] for p in players if p["pcrid"] in roster)
    updated = config.get("member_updated_at", 0) if isinstance(config, dict) else 0
    if format_timestamp(updated) == "未知":
        updated = 0
    summary = (
        f"今日刀表｜游戏日 {start:%m-%d 05:00} 至 {end_text}\n"
        f"名册：{len(roster)}人｜已达3等效：{achieved}人｜参考未完成：{float2int(remaining)}\n"
        f"名册更新：{format_timestamp(updated)}｜最近出刀："
        f"{format_timestamp(max((r['time'] for r in records), default=0))}\n"
        "完整刀=1，尾刀/补偿=0.5；参考未完成量不是精确剩刀，无记录需确认。"
    )
    if period is not None:
        summary = period.label(now) + "\n" + summary
    if not roster:
        summary += "\n成员名册缺失，无法统计未出刀成员，请开启出刀监控刷新名册。"
    elif not updated or now - updated >= 86400:
        summary += "\n名册更新时间未知或已超过24小时，成员变动需确认。"
    if not rows:
        return summary + "\n暂无名册和今日战绩。"
    metadata = f"{datetime.fromtimestamp(now, GAME_TZ):%Y-%m-%d %H:%M}"
    if period is not None:
        metadata += f" · 第{period.id}期 第{period.days(now)}/5天"
    metadata += f" · 游戏日 {start:%m-%d 05:00}–{end_text}"
    note = "完整=1，尾/补=0.5；未完成量仅供参考。"
    if not updated or now - updated >= 86400:
        note = "名册待核验；" + note
    image = _report_image("今日刀表", metadata, [
        (len(roster), "名册成员"), (achieved, "已达3等效"),
        (float2int(remaining), "参考未完成量"), (end_text.split()[-1], "本游戏日截止")], [
        ("", ["成员 / 游戏ID", "完整 / 尾 / 补", "等效", "参考未完成", "最近出刀", "状态"], rows,
         [280, 150, 90, 150, 320, 370])], note)
    return summary + "\n" + image


def preference_members(records, roster):
    names = dict(roster)
    active = defaultdict(set)
    counts = Counter()
    latest = {}
    for record in records:
        uid = str(record["pcrid"])
        if record["time"] >= latest.get(uid, 0):
            latest[uid] = record["time"]
            if uid not in roster:
                names[uid] = record["name"]
        moment = datetime.fromtimestamp(record["time"], GAME_TZ)
        slot = ((moment.hour - 5) % 24) // 2
        active[uid].add((pcr_date(record["time"]).date(), slot))
        counts[uid] += 1
    players = []
    for uid, name in names.items():
        slots = Counter(slot for _, slot in active[uid])
        days = len({day for day, _ in active[uid]})
        levels = sorted(set(slots.values()), reverse=True)
        common = [[slot for slot in sorted(slots) if slots[slot] == count] for count in levels[:2]]
        players.append({"pcrid": uid, "name": name, "days": days,
                        "records": counts[uid], "slots": slots, "common": common})
    return sorted(players, key=lambda p: (-p["days"], p["pcrid"]))


def _slot_text(slots):
    labels = []
    for slot in slots:
        hour = (5 + 2 * slot) % 24
        labels.append(f"{hour:02d}–{(hour + 2) % 24:02d}")
    return "、".join(labels) + ("（并列）" if len(labels) > 1 else "")


def preference_report(records, config, now, activity=""):
    players = preference_members(records, member_roster(config))
    rows = []
    for player in players:
        main, secondary = "无样本", "—"
        if 0 < player["days"] < 3:
            main = "样本不足"
        elif player["days"] >= 3:
            common = player["common"]
            main = _slot_text(common[0]) + f" {player['slots'][common[0][0]]}/{player['days']}天"
            if len(common) > 1:
                secondary = _slot_text(common[1]) + f" {player['slots'][common[1][0]]}/{player['days']}天"
        rows.append([f"{player['name']}\n{player['pcrid']}", main, secondary,
                     player["days"], player["records"]])
    summary = (
        "成员出刀时段偏好｜跨期历史样本（UTC+8）\n"
        "按结算时间统计，每个游戏日每个时段最多计一次活跃。\n"
        "覆盖天数以该成员有记录的游戏日为分母；不足3天不推断偏好。\n"
        f"实际记录范围：{format_timestamp(min((r['time'] for r in records), default=0))}"
        f" 至 {format_timestamp(max((r['time'] for r in records), default=0))}\n"
        "历史习惯仅供安排催刀/询问收尾，不代表当前在线或有空；缺失记录会影响结果。"
    )
    if not rows:
        return summary + "\n暂无成员和战绩样本，请开启出刀监控。\n" + activity
    metadata = (f"跨期历史（UTC+8） · {format_timestamp(min((r['time'] for r in records), default=0))}"
                f" 至 {format_timestamp(max((r['time'] for r in records), default=0))}")
    image = _report_image("成员出刀时段偏好", metadata, [
        (len(players), "成员"), (sum(p["days"] >= 3 for p in players), "样本达标成员"),
        (len(records), "历史战绩"), ("跨期", "统计范围")], [
        ("", ["成员 / 游戏ID", "常见时段", "次常见时段", "活跃天数", "记录数"], rows,
         [280, 360, 460, 140, 120])], "按结算时间统计；不足3天不推断偏好，习惯不代表在线。")
    return summary + "\n" + image + ("\n" + activity if activity else "")


def control_report(bosses, records, queues, names, now, online, event, dispatch=""):
    applications = declared_applications(bosses, queues, now, online, event)
    rows, details, actions = [], [], []
    lowest = min((boss["lap_num"] for boss in bosses if boss["current_hp"]), default=0)
    for boss in bosses:
        order = boss["order"]
        queue = queues.get(order, {"apply": [], "tree": [], "subscribe": []})
        queue_known = order in queues
        applies = applications[order]
        trees = sorted(queue["tree"], key=lambda row: row[1])
        subscriptions = sorted(queue["subscribe"], key=lambda row: (row[1], row[0]))
        current = sum(lap in (0, boss["lap_num"]) for _, lap, _ in subscriptions)
        other = len(subscriptions) - current
        hp, maximum = boss["current_hp"], boss["max_hp"]
        available = boss["available"] and hp > 0
        state = "可挑战" if available else "无法挑战"
        if not online:
            state = "历史" + state
        hp_text = f"{state} {format_bignum(hp)}"
        if maximum:
            hp_text += f" ({hp / maximum:.1%})"
        fighters = boss.get("fighter_num") if online else None
        scene = f"战{fighters if fighters is not None else '未知'} 申{len(queue['apply'])} 约{current}/{other} 树{len(trees)}"
        if not queue_known:
            scene = f"战{fighters if fighters is not None else '未知'} 申未知 约未知 树未知"

        reference = full_damage_reference(records, boss)
        typical = reference["median"]
        historic = f"样本不足 {reference['count']}条/{reference['players']}人"
        knives = "—"
        if typical:
            historic = f"中{format_bignum(int(typical))}/低{format_bignum(reference['lower'])}"
            if online and available:
                knives = f"{math.ceil(hp / typical)}/{math.ceil(hp / reference['lower'])}"
        valid = [row for row in applies if not row["issue"]]
        total = sum(row["declaration"]["damage"] for row in valid)
        capacity = f"{len(valid)}人/{format_bignum(total)}" if online and queue_known else "待确认"
        gap = format_bignum(max(0, hp - total)) if online and available and queue_known else "—"

        hints = []
        if not online:
            hints.append("历史状态")
        elif not available:
            hints.append("无法挑战")
        else:
            if boss["lap_num"] == lowest:
                hints.append("低周目待推进")
            if fighters is None:
                hints.append("挑战人数未知")
            elif fighters:
                hints.append("战斗未结算")
            elif applies:
                hints.append("待安排进刀")
        if online and fighters is not None:
            if applies and fighters == 0:
                actions.append(f"{order}王有申请，暂无人挑战，需确认进刀安排。")
            if fighters >= 2:
                actions.append(f"{order}王有{fighters}人同时挑战，需协调结算。")
        if trees:
            hints.append("挂树需确认")
            actions.append(f"{order}王有{len(trees)}条挂树登记，需确认收尾安排。")
        if any(lap and lap < boss["lap_num"] for _, lap, _ in subscriptions):
            hints.append("预约需确认")
            actions.append(f"{order}王存在已过周目的预约，需重新确认。")
        rows.append([f"{boss['lap_num']}周目{order}王/{boss['stage']}面", hp_text,
                     scene, historic, knives, capacity, gap, "/".join(hints) or "—"])
        details.append(f"=== {order}王｜HP {format_bignum(hp)}/{format_bignum(maximum)}"
                       f"｜完整刀样本 {reference['count']}条/{reference['players']}人 ===")
        for index, row in enumerate(applies, 1):
            elapsed = format_time(max(0, int(now - row["time"]))) or "0秒"
            details.append(f"申请{index}：{_applicant_name(row['uid'], names)}｜已登记{elapsed}"
                           f"｜{declaration_text(row['text'])}｜{row['issue'] or '本次血量有效申报'}")
        for index, (uid, registered, text) in enumerate(trees, 1):
            elapsed = format_time(max(0, int(now - registered))) or "0秒"
            details.append(f"挂树{index}：{_applicant_name(uid, names)}｜已登记{elapsed}｜{declaration_text(text)}")
        for uid, lap, text in subscriptions:
            target = "当前周目" if not lap else f"{lap}周目"
            details.append(f"预约：{_applicant_name(uid, names)}｜{target}｜{text.strip() or '无留言'}")
        if not (applies or trees or subscriptions):
            details.append("无登记。" if queue_known else "登记待确认。")
    heading = (
        "现场队列：战=实际挑战，申=申请，约=当前/其他周目预约，树=挂树。\n"
        "同王同阶段完整刀参考；不足5条或2人不推算。中/低分别为中位数/下四分位取值。\n"
        "申报合计与缺口仅基于本次血量；申报不证明仍有可用刀。血量变化后须重新申报。\n"
        "待处理：\n" + ("\n".join(actions) or "暂无可判断的调度提示。")
    )
    if not online:
        heading = "历史状态；现场登记与申报有效性需确认。\n" + heading
    queues_known = all(boss["order"] in queues for boss in bosses)
    valid_count = sum(not row["issue"] for entries in applications.values() for row in entries)
    image = _report_image("会战指挥台", f"{datetime.fromtimestamp(now, GAME_TZ):%Y-%m-%d %H:%M} · 第{event}期", [
        ("在线" if online else "历史", "现场状态"), (lowest or "—", "最低周目"),
        (valid_count if online and queues_known else "待核验", "有效申报"), (len(actions), "待处理事项")], [
        ("", ["目标", "状态与HP", "现场队列\n战 / 申 / 约 / 树", "完整刀参考\n中 / 低",
              "参考刀数\n中 / 低", "有效申报", "申报缺口", "调度提示"], rows,
         [145, 210, 210, 215, 120, 160, 120, 180])],
        ("历史状态，现场待核验；" if not online else "") + "中/低为完整刀中位数/低位参考，申报需确认可用刀。")
    return (
        image + ("\n" + dispatch if dispatch else ""),
        heading + "\n\n" + "\n".join(details),
    )


def declared_applications(bosses, queues, now, online, event):
    hanging = {uid for queue in queues.values() for uid, _, _ in queue["tree"]}
    result, targets = {}, defaultdict(list)
    for boss in bosses:
        order = boss["order"]
        latest = {}
        for uid, registered, text in queues.get(order, {}).get("apply", []):
            if uid not in latest or registered >= latest[uid][0]:
                latest[uid] = (registered, text)
        rows = []
        for uid, (registered, text) in sorted(latest.items(), key=lambda item: (item[1][0], item[0])):
            declared = decode_declaration(text)
            issue = ""
            if declared is None:
                issue = "未申报伤害"
            elif not online:
                issue = "状态过期，需确认"
            elif type(event) is not int or event <= 0 or declared["event"] != event:
                issue = "会战已变化或未知"
            elif declared["lap"] != boss["lap_num"]:
                issue = "周目已变化，请重新申请"
            elif registered > now:
                issue = "登记时间异常"
            elif now - registered > 1800:
                issue = "申报超过30分钟，请重新申请"
            elif not boss["available"] or not boss["current_hp"]:
                issue = "目标暂不可挑战"
            elif declared["hp"] != boss["current_hp"]:
                # 申请只在击破时清空，血量绑定避免把已结算的刀重复计入。
                issue = "血量已变化，请重新申请"
            elif uid in hanging:
                issue = "有挂树登记，需确认"
            row = {"uid": uid, "time": registered, "text": text, "declaration": declared, "issue": issue}
            rows.append(row)
            if not issue:
                targets[uid].append(row)
        result[order] = rows
    for entries in targets.values():
        if len(entries) > 1:
            for row in entries:
                row["issue"] = "多王申报，请取消申请后确定目标"
    return result


def full_damage_reference(records, boss):
    samples, seen = [], set()
    for record in records:
        if (str(record["boss"]) != str(boss["order"]) or record["flag"] != 0
                or lap2stage(record["lap"]) != boss["stage"]):
            continue
        damage = record.get("damage")
        if type(damage) is not int or damage <= 0:
            continue
        log = record.get("battle_log_id")
        if log:
            key = (record["pcrid"], log)
            if key in seen:
                continue
            seen.add(key)
        samples.append(record)
    damages = sorted(record["damage"] for record in samples)
    enough = len(samples) >= 5 and len({record["pcrid"] for record in samples}) >= 2
    return {"count": len(samples), "players": len({r["pcrid"] for r in samples}),
            "median": median(damages) if enough else None,
            "lower": damages[(len(damages) - 1) // 4] if enough else None}
