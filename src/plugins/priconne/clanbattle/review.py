"""本期复盘：五日节奏、成员明细和同阶段刀伤。"""

from bisect import bisect_right
from collections import Counter, defaultdict
from datetime import datetime, timedelta
import io
import math
from random import Random
from statistics import median

from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.font_manager import FontProperties
from PIL import Image

from ..compat.convert2img import _load_font
from ..util.tools import lap2stage
from .period import GAME_TZ
from .render import _report_image, _chart_report_image
from .reports import member_roster
from .settlement import uncertain

REVIEW_PAGES = ("overview", "members", "bosses", "distribution", "ranges")
DAMAGE_BOUNDS = (300_000_000, 320_000_000, 350_000_000)
RANGE_LABELS = ("<3.0亿", "3.0–3.2亿", "3.2–3.5亿", "≥3.5亿")
_PLOT_FONT = FontProperties(fname=str(_load_font(23).path), size=17)


def build_review(records, config, now, period, group_id):
    filtered, seen = [], set()
    for record in records:
        if not period.start <= record["time"] < min(period.end, now + 1):
            continue
        log = record.get("battle_log_id")
        key = (str(record["pcrid"]), log)
        if log and key in seen:
            continue
        if log:
            seen.add(key)
        filtered.append(record)
    config = config or {}
    roster = member_roster(config) if config.get("clan_battle_id") in (None, period.id) else {}
    names = dict(roster)
    daily, members, bosses, full = [[] for _ in range(5)], defaultdict(list), defaultdict(list), defaultdict(list)
    first = datetime.fromtimestamp(period.start, GAME_TZ).date()
    for record in filtered:
        uid = str(record["pcrid"])
        names.setdefault(uid, str(record["name"]))
        day = ((datetime.fromtimestamp(record["time"], GAME_TZ) - timedelta(hours=5)).date() - first).days
        daily[day].append(record)
        members[uid].append(record)
        stage, boss = lap2stage(record["lap"]), int(record["boss"])
        bosses[stage, boss].append(record)
        if record["flag"] == 0:
            full[stage, boss, uid].append(record["damage"])
    stages = {stage for stage, boss, uid in full}
    stage = next((value for value in ("D", "C", "B") if value in stages), None)
    samples = {key: values for key, values in full.items() if key[0] == stage}
    repeated = Counter(names.values())
    labels = {uid: name if repeated[name] == 1 else f"{name}\n{uid}" for uid, name in names.items()}
    last = max((r["time"] for r in filtered), default=None)
    date = datetime.fromtimestamp(period.start, GAME_TZ)
    end = datetime.fromtimestamp(period.end - 1, GAME_TZ)
    coverage = f"截至{datetime.fromtimestamp(last, GAME_TZ):%m-%d %H:%M}" if last is not None else "暂无战绩"
    return dict(records=filtered, roster=roster, names=names, labels=labels, daily=daily, members=members,
                bosses=bosses, samples=samples, stage=stage, period=period, group_id=group_id,
                metadata=f"第{period.id}期｜{date:%Y-%m-%d}～{end:%m-%d}｜群{group_id}｜{coverage}")


def _counts(rows):
    values = Counter(r["flag"] for r in rows)
    pending = sum(uncertain(row) for row in rows)
    return (f"{values[0]}/{values[1]}/{values[.5]}" + (f"\n待核验{pending}" if pending else "")) if rows else "—"


def _damage(rows):
    return sum(r["damage"] for r in rows)


def _overview(data):
    total = _damage(data["records"])
    rows = []
    for day, records in enumerate(data["daily"]):
        start = data["period"].start + day * 86400
        date = datetime.fromtimestamp(start, GAME_TZ)
        slots = Counter((r["time"] - start) // 7200 for r in records)
        peak = max(slots.values(), default=0)
        times = []
        for slot, count in sorted(slots.items()):
            if count == peak:
                left = datetime.fromtimestamp(start + slot * 7200, GAME_TZ)
                right = datetime.fromtimestamp(min(start + (slot + 1) * 7200, data["period"].end), GAME_TZ)
                times.append(f"{left:%H}–{right:%H}")
        late = sum(r["time"] >= start + 16 * 3600 for r in records)
        rows.append([f"{date:%m-%d}\n第{day + 1}天", _counts(records), f"{_damage(records)/1e8:.2f}",
                     f"{_damage(records)/total:.1%}" if total else "—", len({r["pcrid"] for r in records}),
                     "、".join(times) + f"\n{peak}次（{peak/len(records):.1%}）" if records else "—",
                     f"{late}次\n{late/len(records):.1%}" if records else "—"])
    flags = Counter(r["flag"] for r in data["records"])
    return _report_image("本期复盘 · 总览", data["metadata"], [
        (f"{total/1e8:.2f}亿", "累计伤害"), (flags[0], "完整刀次数"),
        (flags[1], "尾刀次数"), (flags[.5], "补偿刀次数")], [
        ("五日节奏", ["活动日", "完整/尾/补", "伤害（亿）", "伤害占比", "人数", "结算高峰", "21–05结算"],
         rows, [190, 210, 170, 110, 110, 260, 310])],
        "05:00换日，末日23:59:59结束；刀型按默认配对推断，伤害保留原始值。")


def _members(data):
    rows = []
    for uid in sorted(data["names"], key=lambda uid: (-_damage(data["members"].get(uid, [])), uid)):
        records = data["members"].get(uid, [])
        cells = [_counts([r for r in daily if str(r["pcrid"]) == uid]) for daily in data["daily"]]
        rows.append([data["labels"][uid], *cells, _counts(records), f"{_damage(records)/1e8:.2f}"])
    date = datetime.fromtimestamp(data["period"].start, GAME_TZ)
    columns = ["成员", *[f"{date + timedelta(days=day):%m-%d}\n第{day + 1}天" for day in range(5)],
               "整期合计", "总伤害（亿）"]
    return _report_image("本期复盘 · 成员五日明细", data["metadata"], [
        (len(data["names"]), "成员"), ("5天", "活动天数"), ("15刀/人", "整期额度"),
        (len(data["records"]), "已保存战绩")], [
        ("", columns, rows or [["暂无名册与战绩", *["—"] * 7]], [290, 140, 140, 140, 140, 140, 160, 210])],
        "单元格按默认配对计完整/尾/补；待核验单列，—为无记录。")


def _bosses(data):
    sections = []
    for stage, laps in (("B", "1–6周目"), ("C", "7–22周目"), ("D", "23周目起")):
        rows = []
        for boss in range(1, 6):
            records = data["bosses"].get((stage, boss), [])
            values = [r["damage"] for r in records if r["flag"] == 0]
            flags = Counter(r["flag"] for r in records)
            rows.append([f"{boss}王", f"{median(values)/1e8:.2f}" if values else "—",
                         flags[0], flags[1], flags[.5], f"{_damage(records)/1e8:.2f}"])
        sections.append((f"{stage}阶段｜{laps}", ["BOSS", "完整刀中位数（亿）", "完整刀次数", "尾刀次数", "补偿次数", "总伤害（亿）"],
                         rows, [140, 340, 170, 170, 170, 370]))
    records = data["records"]
    laps = f"{min(r['lap'] for r in records)}–{max(r['lap'] for r in records)}" if records else "—"
    return _report_image("本期复盘 · 分王表现", data["metadata"], [
        (3, "阶段"), (15, "王×阶段分组"), (sum(r["flag"] == 0 for r in records), "完整刀样本"),
        (laps, "覆盖周目")], sections, "中位数取本期同王同阶段推断完整刀的原始伤害；待核验不混入样本。")


def damage_ranges(data):
    result = defaultdict(list)
    for (stage, boss, uid), values in data["samples"].items():
        value = median(values)
        result[bisect_right(DAMAGE_BOUNDS, value), boss].append((uid, value, len(values)))
    return result


def _ranges(data):
    cells = damage_ranges(data)
    rows = []
    for bucket in reversed(range(4)):
        row = [RANGE_LABELS[bucket]]
        for boss in range(1, 6):
            entries = sorted(cells[bucket, boss], key=lambda item: (-item[1], item[0]))
            row.append("\n".join(f"{data['labels'][uid]}（{count}）" for uid, value, count in entries) or "—")
        rows.append(row)
    columns = ["刀伤范围"]
    for boss in range(1, 6):
        values = [values for (stage, b, uid), values in data["samples"].items() if b == boss]
        columns.append(f"{boss}王\n{len(values)}人 · {sum(map(len, values))}次")
    return _report_image("五王刀伤分档 · 成员表", data["metadata"], [
        (len({uid for stage, boss, uid in data["samples"]}), "有完整刀成员"),
        (len(data["samples"]), "成员×BOSS"), (sum(map(len, data["samples"].values())), "完整刀样本"),
        (4, "伤害档位")], [(f"{data['stage']}阶段｜完整刀中位数分档" if data["stage"] else "暂无完整刀样本",
                             columns, rows, [160, 240, 240, 240, 240, 240])],
        "按推断完整刀的原始伤害中位数分档；括号为样本数；区间含下限、不含上限。")


def _distribution(data):
    values = [[value / 1e8 for (stage, b, uid), samples in data["samples"].items() if b == boss
               for value in samples] for boss in range(1, 6)]
    count = sum(map(len, values))
    records = [r for r in data["records"] if r["flag"] == 0 and lap2stage(r["lap"]) == data["stage"]]
    cards = [(count, "完整刀样本"), (5, "BOSS数量"),
             (f"{data['stage']}阶段" if data["stage"] else "—", "同阶段比较"),
             (f"{min(r['lap'] for r in records)}–{max(r['lap'] for r in records)}" if records else "—", "样本周目")]
    if not count:
        return _report_image("五王完整刀伤分布", data["metadata"], cards,
                             [("", ["样本情况"], [["本期暂无完整刀样本"]], [1360])], "仅取本期同阶段完整刀。")
    figure = Figure(figsize=(13.6, 7.4), dpi=100, facecolor="white")
    FigureCanvasAgg(figure)
    ax = figure.subplots()
    figure.subplots_adjust(left=.085, right=.985, bottom=.15, top=.86)
    positions = [boss for boss, group in enumerate(values, 1) if group]
    groups = [group for group in values if group]
    ax.boxplot(groups, positions=positions, widths=.44, patch_artist=True, showfliers=False,
               boxprops={"facecolor": "#E5EBF6", "edgecolor": "#245BBA", "linewidth": 1.8},
               medianprops={"color": "#245BBA", "linewidth": 2.8},
               whiskerprops={"color": "#53647B", "linewidth": 1.6},
               capprops={"color": "#53647B", "linewidth": 1.6})
    rng = Random(data["period"].id)
    for boss, group in enumerate(values, 1):
        if group:
            ax.scatter([boss + rng.uniform(-.17, .17) for _ in group], group,
                       s=27, alpha=.48, color="#4F80C9", edgecolors="none", zorder=3)
        ax.text(boss, 1.025, f"中位 {median(group):.2f}亿" if group else "无样本",
                transform=ax.get_xaxis_transform(), ha="center", va="bottom", color="#245BBA", fontproperties=_PLOT_FONT)
    ax.set_xticks(range(1, 6), [f"{boss}王\n{len(group)}次" for boss, group in enumerate(values, 1)])
    ax.set_xlim(.5, 5.5)
    lower = math.floor(min(map(min, groups)) * 2) / 2
    upper = max(lower + .5, math.ceil(max(map(max, groups)) * 2) / 2)
    ax.set_ylim(lower, upper)
    step = max(.5, math.ceil((upper - lower) / 7 * 2) / 2)
    ax.set_yticks([lower + step * index for index in range(math.floor((upper - lower) / step) + 1)])
    ax.set_ylabel("刀伤（亿）", fontproperties=_PLOT_FONT, color="#53647B", labelpad=16)
    for label in ax.get_xticklabels() + ax.get_yticklabels():
        label.set_fontproperties(_PLOT_FONT)
    ax.tick_params(axis="both", length=0, pad=13, colors="#53647B")
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.spines["bottom"].set_color("#CBD5E5")
    ax.grid(axis="y", color="#E5EBF6", linewidth=1)
    ax.set_axisbelow(True)
    buffer = io.BytesIO()
    figure.savefig(buffer, format="png", dpi=100)
    chart = Image.open(buffer).convert("RGB")
    return _chart_report_image("五王完整刀伤分布", data["metadata"], cards,
                               f"{data['stage']}阶段｜五王伤害分布", chart,
                               "点＝原始刀伤；横线＝中位数；箱体＝中间50%；仅取推断完整刀样本。")


def render_review(data, page):
    return {"overview": _overview, "members": _members, "bosses": _bosses,
            "distribution": _distribution, "ranges": _ranges}[page](data)
