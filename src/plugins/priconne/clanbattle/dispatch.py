"""本期人员联系与合刀建议；出刀时间不是在线状态，等效量不是可用刀。"""

from collections import Counter, defaultdict
from datetime import datetime, timedelta
from itertools import combinations
from statistics import median

from ..util.tools import lap2stage
from .base import float2int, format_bignum
from .render import _report_image
from .reports import GAME_TZ, daily_members, declared_applications, member_roster, preference_members
from .sql import pcr_date


def valid_member_links(raw, roster):
    if not isinstance(raw, dict):
        return {}
    links = {str(qq): str(uid) for qq, uid in raw.items()
             if str(qq).isascii() and str(qq).isdigit() and len(str(qq)) <= 20
             and not str(qq).startswith("0") and str(uid) in roster}
    counts = Counter(links.values())
    return {qq: uid for qq, uid in links.items() if counts[uid] == 1}


def register_member_link(raw, roster, qq, uid):
    qq, uid = str(qq), str(uid)
    if uid not in roster:
        raise ValueError("游戏ID不在当前群名册，请开启出刀监控刷新名册后重试。")
    links = dict(raw) if isinstance(raw, dict) else {}
    if qq in links and str(links[qq]) != uid:
        raise ValueError("该QQ已有登记，请先【取消会战成员登记】再登记新游戏ID。")
    if any(str(other) != qq and str(value) == uid for other, value in links.items()):
        raise ValueError("该游戏ID已由其他QQ登记，请群管理员核验并取消旧登记后重试。")
    links[qq] = uid
    return links


def build_dispatch(records, config, now, period, links=None, bosses=None, queues=None, ready=False):
    data = {"now": now, "period": period, "active": bool(period and period.active(now)),
            "members": [], "active_members": [], "pending": [], "windows": [], "unplanned": [],
            "pairs": [], "prior_days": 0, "ready": False, "unlinked": 0}
    if not data["active"]:
        return data
    roster = member_roster(config)
    links = valid_member_links(links, roster)
    game_to_qq = {uid: qq for qq, uid in links.items()}
    queues = queues or {}
    ready = bool(ready and bosses and all(b["order"] in queues for b in bosses))
    data["ready"] = ready
    day = int(pcr_date(now).timestamp())
    cutoff = min(period.end, day + 86400)
    slot = int((now - day) // 7200)
    data.update(slot=slot, cutoff=cutoff, prior_days=max(0, min(4, (day - period.start) // 86400)))
    current, seen = [], set()
    for record in records:
        if not period.start <= record["time"] <= now or record["time"] >= period.end:
            continue
        log = record.get("battle_log_id")
        if log:
            key = (str(record["pcrid"]), log)
            if key in seen:
                continue
            seen.add(key)
        current.append(record)
    habits = {p["pcrid"]: p for p in preference_members([r for r in current if r["time"] < day], roster)}
    members = {p["pcrid"]: p for p in daily_members([r for r in current if r["time"] >= day], roster)
               if p["pcrid"] in roster}
    applications = declared_applications(bosses or [], queues, now, ready, period.id)
    valid = {str(row["uid"]): row for rows in applications.values() for row in rows if not row["issue"]}
    applied, subscribed, hanging = defaultdict(set), defaultdict(set), set()
    for order, queue in queues.items():
        for qq, _, _ in queue.get("apply", []):
            applied[str(qq)].add(order)
        for qq, lap, _ in queue.get("subscribe", []):
            subscribed[str(qq)].add((order, lap))
        hanging.update(str(row[0]) for row in queue.get("tree", []))
    boss_by_order = {b["order"]: b for b in bosses or []}
    for uid, player in members.items():
        qq = game_to_qq.get(uid)
        player.update(qq=qq, slots=habits[uid]["slots"], blocked="", target=None,
                      declared=valid.get(qq), has_apply=bool(applied.get(qq)))
        player["recent"] = bool(player["latest"] and 0 <= now - player["latest"]["time"] <= 1800)
        player["hits"] = player["slots"][slot]
        if player["pending"]:
            player["blocked"] = "刀型待核验"
        elif qq in hanging:
            player["blocked"] = "挂树，待结算"
        elif len(applied[qq]) > 1 or len({order for order, _ in subscribed[qq]}) > 1:
            player["blocked"] = "多王登记"
        elif applied[qq] and subscribed[qq] and applied[qq] != {order for order, _ in subscribed[qq]}:
            player["blocked"] = "登记冲突"
        elif subscribed[qq]:
            order, lap = next(iter(subscribed[qq]))
            boss = boss_by_order.get(order)
            if boss is None or lap not in (0, boss["lap_num"]):
                player["blocked"] = "预约周目需确认"
            else:
                player["target"] = order
        if player["blocked"]:
            player["declared"] = None
    rank = lambda p: (-bool(p["declared"]), -p["recent"], -p["hits"], -p["remaining"], p["pcrid"])
    data["members"] = sorted(members.values(), key=rank)
    data["active_members"] = [p for p in data["members"] if p["declared"] or p["recent"]
                              or (p["remaining"] > 0 and p["hits"] >= 2)]
    data["pending"] = [p for p in data["members"] if p["remaining"] > 0 or p["declared"] or p["pending"]]
    for index in range(slot, 12):
        left, right = max(now, day + index * 7200), min(cutoff, day + (index + 1) * 7200)
        if left >= right:
            continue
        final = right == period.end
        label = (datetime.fromtimestamp(left, GAME_TZ).strftime("%H:%M") + "–"
                 + datetime.fromtimestamp(right - 1 if final else right, GAME_TZ).strftime("%H:%M:%S" if final else "%H:%M"))
        data["windows"].append({"slot": index, "start": left, "end": right, "label": label, "members": []})
    assigned = {}
    for player in data["pending"]:
        if player["blocked"]:
            data["unplanned"].append(player)
            continue
        best = max(data["windows"], key=lambda w: (player["slots"][w["slot"]], -w["start"]))
        if player["recent"] or player["declared"]:
            best = data["windows"][0]
        if not player["slots"][best["slot"]] and not (player["recent"] or player["declared"]):
            data["unplanned"].append(player)
        else:
            best["members"].append(player)
            assigned[player["pcrid"]] = best["slot"]
    for window in data["windows"]:
        window["members"].sort(key=lambda p: (-bool(p["declared"]), -p["recent"],
                                               -p["slots"][window["slot"]], -p["remaining"], p["pcrid"]))

    damage = defaultdict(list)
    for record in current:
        if record["flag"] == 0 and type(record.get("damage")) is int and record["damage"] > 0:
            damage[(str(record["pcrid"]), str(record["boss"]), lap2stage(record["lap"]))].append(record["damage"])
    targets = bosses or []
    if not targets and current:
        stage = lap2stage(max(r["lap"] for r in current))
        targets = [{"order": order, "stage": stage} for order in range(1, 6)]
    targets = sorted(targets, key=lambda b: (b.get("lap_num", 0), b["order"]))
    used = set()
    for declared_mode in (True, False):
        for boss in targets:
            order = boss["order"]
            if any(pair["order"] == order for pair in data["pairs"]):
                continue
            if ready and (not boss["available"] or boss["current_hp"] <= 0):
                continue
            if declared_mode:
                candidates = [p for p in members.values() if ready and p["declared"]
                              and p["pcrid"] not in used and p["pcrid"] in assigned
                              and p["declared"] in applications.get(order, [])]
            else:
                candidates = [p for p in members.values() if p["pcrid"] not in used and not p["blocked"]
                              and not p["has_apply"] and assigned.get(p["pcrid"]) == slot
                              and p["remaining"] >= 1 and (p["recent"] or p["hits"] >= 2)
                              and p["target"] in (None, order)
                              and len(damage[(p["pcrid"], str(order), boss["stage"])]) >= 2]
            if len(candidates) < 2:
                continue
            def pair_score(pair):
                score = (min(p["hits"] for p in pair), sum(p["hits"] for p in pair),
                         sum(min(4, len(damage[(p["pcrid"], str(order), boss["stage"])])) for p in pair))
                if declared_mode:
                    total = sum(p["declared"]["declaration"]["damage"] for p in pair)
                    hp = boss["current_hp"]
                    return (total >= hp, -abs(total - hp), *score)
                return score
            chosen = max(combinations(sorted(candidates, key=lambda p: p["pcrid"]), 2), key=pair_score)
            samples = [damage[(p["pcrid"], str(order), boss["stage"])] for p in chosen]
            estimates = ([p["declared"]["declaration"]["damage"] for p in chosen] if declared_mode
                         else [int(median(values)) for values in samples])
            gap, status = None, "历史待申报"
            if declared_mode:
                fighters = boss.get("fighter_num")
                status = "挑战人数未知" if fighters is None else "有人挑战，先协调"
                if fighters == 0:
                    gap = boss["current_hp"] - sum(estimates)
                    status = "申报有缺口" if gap > 0 else "申报覆盖\n待确认轴"
            data["pairs"].append({"order": order, "stage": boss["stage"], "members": chosen,
                                  "samples": samples, "damage": estimates, "declared": declared_mode,
                                  "gap": gap, "status": status})
            used.update(p["pcrid"] for p in chosen)
    data["unlinked"] = sum(qq not in links for qq in valid)
    return data


def _inactive_notice(data):
    period = data["period"]
    return (period.label(data["now"]) + "\n当前不在会战期间。" if period else
            "期次缺失，请【更新wiki数据库】。")


def _identity(player):
    return f"{player['name']}\n{player['pcrid']}" + (f"\nQQ {player['qq']}" if player["qq"] else "")


def _evidence(data, player, slot):
    if not data["prior_days"]:
        return "首日无样本"
    return f"前{data['prior_days']}天：{player['slots'][slot]}/{data['prior_days']}天"


def activity_report(data, group_id):
    if not data["active"]:
        return _inactive_notice(data)
    period, now = data["period"], data["now"]
    metadata = (f"群{group_id} · {datetime.fromtimestamp(now, GAME_TZ):%Y-%m-%d %H:%M}"
                f" · 第{period.id}期 第{period.days(now)}/5天")
    rows = []
    for player in data["active_members"]:
        signal = ("有效申报" if player["declared"] else "近30分钟结算" if player["recent"]
                  else "时段偏好")
        action = player["blocked"] or ("仅活跃线索" if not player["remaining"] else "待联系")
        rows.append([_identity(player), signal, _evidence(data, player, data["slot"]),
                     float2int(player["remaining"]),
                     datetime.fromtimestamp(player["latest"]["time"], GAME_TZ).strftime("%H:%M:%S") if player["latest"] else "无记录",
                     action])
    if not rows:
        rows = [["暂无候选", "等待结算或申报", "样本不足", "—", "—", "确认时间"]]
    return _report_image("可能活跃成员", metadata, [
        (len(data["pending"]), "待核验成员"), (sum(p["recent"] for p in data["members"]), "近30分钟有结算"),
        (len(data["active_members"]), "优先联系"),
        (datetime.fromtimestamp(data["cutoff"] - 1, GAME_TZ).strftime("%H:%M:%S"), "本游戏日截止")], [
        ("", ["成员", "活跃线索", "本期时段记录", "参考未完成", "今日最近结算", "状态"], rows,
         [280, 220, 250, 150, 200, 260])],
        ("数据待核验；" if not data["ready"] else "") + "未完成量仅供参考，出刀前确认可用刀。")


def coordination_reports(data, group_id):
    if not data["active"]:
        return _inactive_notice(data)
    period, now = data["period"], data["now"]
    metadata = (f"群{group_id} · {datetime.fromtimestamp(now, GAME_TZ):%Y-%m-%d %H:%M}"
                f" · 第{period.id}期 第{period.days(now)}/5天")
    rows = []
    for pair in data["pairs"]:
        players = pair["members"]
        evidence = "\n".join(f"{p['name']}\n{_evidence(data, p, data['slot'])}" for p in players)
        source = []
        for player, samples, damage in zip(players, pair["samples"], pair["damage"]):
            if pair["declared"]:
                declared = player["declared"]["declaration"]
                kind = "完整90秒" if declared["kind"] == "full" else f"补偿{declared['seconds']}秒"
                source.append(f"{player['name']}：申报{kind} {format_bignum(damage)}")
            else:
                source.append(f"{player['name']}：{len(samples)}条 / {format_bignum(damage)}")
        total = f"{format_bignum(sum(pair['damage']))}\n" + ("申报合计" if pair["declared"] else "历史合计")
        if pair["gap"] is not None:
            total += (f"\n缺口{format_bignum(pair['gap'])}" if pair["gap"] > 0
                      else f"\n超出HP {format_bignum(-pair['gap'])}")
        rows.append([f"{pair['order']}王\n{pair['stage']}面",
                     "\n+\n".join(f"{p['name']}\n{p['pcrid']}" for p in players), evidence,
                     "\n".join(source), total, pair["status"]])
    if not rows:
        rows = [["—", "暂无组合", "样本或身份不足", "登记并申报伤害", "—", "待核验"]]
    declared_count = sum(pair["declared"] for pair in data["pairs"])
    pairs = _report_image("合刀候选", metadata, [
        (f"{len(data['pairs'])}组", "候选组合"), (f"{declared_count}组", "有效申报"),
        (f"{len(data['pairs']) - declared_count}组", "历史候选"), ("待确认", "可用刀与轴")], [
        ("", ["目标", "成员 / 游戏ID", "本期时段记录", "伤害：申报 / 历史中位数", "合计 / 缺口", "状态"],
         rows, [110, 280, 250, 340, 200, 180])],
        ("数据待核验；" if not data["ready"] else "") + "出刀前确认伤害与轴。"
        + (f"{data['unlinked']}人未登记游戏ID。" if data["unlinked"] else ""))
    sections = []
    shown_windows = [w for w in data["windows"] if w["members"]] or data["windows"][:1]
    for window in shown_windows:
        members = window["members"]
        action = "待申报" if window["slot"] == data["slot"] else "待联系"
        plan_rows = [[_identity(p), ("有效申报；" if p["declared"] else "近30分结算；" if p["recent"] else "")
                      + _evidence(data, p, window["slot"]), float2int(p["remaining"]),
                      ("待进刀" if p["declared"] else "申请待核验" if p["has_apply"] else action)]
                     for p in members]
        if not plan_rows:
            plan_rows = [["暂无候选", "待同步", "—", "待确认"]]
        sections.append((window["label"] + ("  现在联系" if window["slot"] == data["slot"] else "  提前联系"),
                         ["成员", "时段依据", "参考未完成", "状态"], plan_rows, [300, 380, 260, 420]))
    if data["unplanned"]:
        sections.append(("待确认", ["成员", "原因", "参考未完成", "状态"],
                         [[_identity(p), p["blocked"] or "剩余时段无样本", float2int(p["remaining"]), "待联系"]
                          for p in data["unplanned"]], [300, 380, 260, 420]))
    plan = _report_image("出刀规划", metadata, [
        (len(data["pending"]), "待核验成员"), (float2int(sum(p["remaining"] for p in data["pending"] if not p["pending"])), "参考未完成量"),
        (len(data["windows"]), "剩余时段"),
        (datetime.fromtimestamp(data["cutoff"] - 1, GAME_TZ).strftime("%H:%M:%S"), "本游戏日截止")], sections,
        ("数据待核验；" if not data["ready"] else "") + "未完成量仅供参考，出刀后刷新。")
    return pairs + "\n" + plan
