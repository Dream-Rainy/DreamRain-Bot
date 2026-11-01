from datetime import datetime, timedelta, timezone
import base64
import io
import re

from PIL import Image
import pytest


@pytest.fixture()
def review(app):
    from src.plugins.priconne.clanbattle import review
    from src.plugins.priconne.clanbattle.period import BattlePeriod

    start = int(datetime(2026, 9, 24, 5, tzinfo=timezone(timedelta(hours=8))).timestamp())
    return review, BattlePeriod(42, start, start + 5 * 86400 - 5 * 3600)


def record(uid, moment, damage, log, boss=1, lap=23, flag=0, remain_time=90, battle_time=90):
    return dict(pcrid=uid, name=f"成员{uid}", time=moment, damage=damage,
                battle_log_id=log, boss=str(boss), lap=lap, flag=flag,
                remain_time=remain_time, battle_time=battle_time)


def test_review_isolates_event_future_and_game_days_and_keeps_zero_record_roster(review):
    module, period = review
    rows = [record(1, period.start - 1, 900, 1), record(1, period.start, 100, 2),
            record(1, period.start + 86400 - 1, 200, 3, flag=1),
            record(1, period.start + 86400, 300, 4, flag=.5),
            record(1, period.end - 1, 400, 5), record(1, period.end, 800, 6)]
    config = dict(clan_battle_id=42, member_by_id={"1": "同名", "2": "同名"})
    data = module.build_review(rows + [rows[1]], config, period.end, period, 456)
    assert [r["battle_log_id"] for r in data["records"]] == [2, 3, 4, 5]
    assert [len(day) for day in data["daily"]] == [2, 1, 0, 0, 1]
    assert data["labels"] == {"1": "同名\n1", "2": "同名\n2"}
    assert "2" not in data["members"] and len(data["names"]) == 2
    early = module.build_review(rows, config, period.start, period, 456)
    assert [r["battle_log_id"] for r in early["records"]] == [2]
    other_roster = module.build_review(rows, dict(clan_battle_id=41, member_by_id={"99": "旧期成员"}),
                                       period.end, period, 456)
    assert "99" not in other_roster["names"]


def test_member_ranges_use_unrounded_same_boss_stage_90s_medians(review):
    module, period = review
    rows = [record(1, period.start, 299_999_999, 1), record(2, period.start, 300_000_000, 2),
            record(3, period.start, 310_000_000, 3), record(3, period.start, 330_000_000, 4),
            record(4, period.start, 350_000_000, 5),
            record(3, period.start, 9_000_000_000, 6, flag=.5, remain_time=60, battle_time=60),
            record(3, period.start, 9_000_000_000, 7, lap=10),
            record(1, period.start, 400_000_000, 8, boss=2)]
    data = module.build_review(rows, {}, period.end, period, 456)
    groups = module.damage_ranges(data)
    assert data["stage"] == "D"
    assert groups[0, 1] == [("1", 299_999_999, 1)]
    assert groups[1, 1] == [("2", 300_000_000, 1)]
    assert groups[2, 1] == [("3", 320_000_000, 2)]
    assert groups[3, 1] == [("4", 350_000_000, 1)]
    assert groups[0, 2] == [("1", 400_000_000, 1)]
    assert sum(len(entries) for entries in groups.values()) == 5


def test_natural_ranges_find_separated_clusters_without_splitting_ties_or_weighting_attack_counts(review):
    module, _ = review
    values = [100_000_000, 100_000_000, 101_000_000, 200_000_000, 201_000_000,
              300_000_000, 301_000_000, 400_000_000, 401_000_000]
    samples = {("D", 1, str(index)): [value] * (50 if index == 0 else 1)
               for index, value in enumerate(values)}
    groups = module.damage_ranges(dict(range_samples=samples))
    assert [[row[1] for row in groups[bucket, 1]] for bucket in range(4)] == [
        values[:3], values[3:5], values[5:7], values[7:]]
    assert groups[0, 1][0][2] == 50
    samples.update({("D", 2, str(index)): [value * 10] for index, value in enumerate(values)})
    other = module.damage_ranges(dict(range_samples=samples))
    assert [other[bucket, 1] for bucket in range(4)] == [groups[bucket, 1] for bucket in range(4)]
    assert sum(len(other[bucket, boss]) for bucket in range(4) for boss in (1, 2)) == 18


def test_range_samples_use_duration_instead_of_kind_and_keep_raw_damage(review):
    module, period = review
    rows = [record(index, period.start, index * 100, index, flag=flag)
            for index, flag in enumerate((0, 1, .5, None), 1)]
    rows[1]["effective_damage"] = 1
    for index, (start, used) in enumerate(((90, 89), (89, 89), (90, None), (None, 90), ("90", 90)), 10):
        rows.append(record(index, period.start, 99999, index, remain_time=start, battle_time=used))
    missing = record(20, period.start, 99999, 20)
    missing.pop("remain_time")
    rows += [missing, record(21, period.start - 1, 99999, 21),
             record(22, period.end, 99999, 22), record(23, period.start, 99999, 23, lap=10)]
    data = module.build_review(rows, {}, period.end, period, 456)
    assert data["range_stage"] == "D"
    assert data["range_samples"] == {("D", 1, str(index)): [index * 100] for index in range(1, 5)}
    assert module.damage_ranges(data)[1, 1] == [("2", 200, 1)]


def test_range_stage_is_independent_of_unchanged_distribution_samples(review):
    module, period = review
    rows = [record(1, period.start, 100, 1, lap=10, battle_time=89),
            record(2, period.start, 900, 2, flag=1)]
    data = module.build_review(rows, {}, period.end, period, 456)
    assert data["stage"] == "C" and data["samples"] == {("C", 1, "1"): [100]}
    assert data["range_stage"] == "D" and data["range_samples"] == {("D", 1, "2"): [900]}
    rows[1]["battle_time"] = 89
    empty_ranges = module.build_review(rows, {}, period.end, period, 456)
    assert empty_ranges["range_stage"] is None and empty_ranges["range_samples"] == {}
    assert empty_ranges["samples"] == data["samples"]


def test_member_matrix_reuses_recorded_counts_marks_pending_and_never_caps_excess(review, monkeypatch):
    module, period = review
    rows = []
    def add(day, flag=0, **extra):
        row = record(1, period.start + day * 86400, 100, len(rows) + 1, flag=flag)
        row.update(extra)
        rows.append(row)
    for _ in range(3):
        add(0)
    add(1, 1)
    add(1, .5)
    add(2, None, raw_flag=0)
    add(2, None, damage=50)
    for _ in range(16):
        add(3)
    rows.append(record(1, period.end - 1, 100, len(rows) + 1, flag=.5))
    rows.append(record(1, period.end, 999999, len(rows) + 1))
    data = module.build_review(rows, dict(member_by_id={"1": "同名", "2": "同名"}), period.end, period, 456)
    captured = []
    monkeypatch.setattr(module, "_report_image", lambda *args: captured.append(args) or "图片")
    module._members(data)
    table = captured[0][3][0][2]
    active, empty = table
    assert active[0] == "同名\n1" and empty[0] == "同名\n2"
    assert [cell["text"] for cell in active[1:7]] == ["3刀", "1刀", "1刀*", "16刀*", "0.5刀", "21.5刀*"]
    assert active[2]["detail"] == "整0 尾1 补1" and active[2]["color"] == active[3]["color"]
    assert active[4]["color"] == active[6]["color"] == active[1]["color"] == "#118763"
    assert all(cell["text"] == "—" for cell in empty[1:7])
    assert active[-1] == f"{sum(row['damage'] for row in rows[:-1])/1e8:.2f}"
    assert rows[5]["flag"] is None and rows[5]["raw_flag"] == 0


def test_member_matrix_colors_gradually_increase_and_keep_excess_green_with_one_marker(review):
    module, _ = review
    def cell(amount, quota=3, pending=0):
        return module._member_knife_cell(dict(latest={}, pending=pending, knife=amount,
                                               full=0, tail=0, comp=0), quota)
    assert cell(0)["color"] == "#667386" and cell(.5)["color"] == "#c94354"
    colors = [cell(amount)["color"] for amount in (.5, 1, 1.5, 2, 2.5, 3)]
    assert len(set(colors)) == 6
    assert [int(color[1:3], 16) for color in colors] == sorted((int(color[1:3], 16) for color in colors), reverse=True)
    assert [int(color[3:5], 16) for color in colors] == sorted(int(color[3:5], 16) for color in colors)
    assert cell(3)["text"] == "3刀" and cell(4, pending=1)["text"] == "4刀*"
    assert cell(4)["color"] == cell(16, quota=15)["color"] == cell(3)["color"] == "#118763"
    assert cell(12.5, quota=15)["color"] == cell(2.5)["color"]


def test_member_matrix_future_days_and_game_day_boundary(review, monkeypatch):
    module, period = review
    now = period.start + 86400
    rows = [record(1, now - 1, 100, 1), record(1, now, 100, 2), record(1, now + 1, 100, 3)]
    data = module.build_review(rows, {}, now, period, 456)
    captured = []
    monkeypatch.setattr(module, "_report_image", lambda *args: captured.append(args) or "图片")
    module._members(data)
    headings, table = captured[0][3][0][1:3]
    assert "进行中" in headings[2] and all("未到" in heading for heading in headings[3:6])
    assert [cell["text"] for cell in table[0][1:7]] == ["1刀", "1刀", "—", "—", "—", "2刀"]


@pytest.mark.parametrize("values,expected", [([], 0), ([0, 0], 1), ([1, 1, 2, 2, 3], 3)])
def test_natural_ranges_reduce_group_count_for_empty_or_repeated_values(review, values, expected):
    module, _ = review
    entries = [(str(index), value, 1) for index, value in enumerate(values)]
    groups = module._natural_groups(entries)
    assert len(groups) == expected
    assert [entry for group in groups for entry in group] == entries


def test_all_empty_reports_and_partial_zero_damage_chart_render_without_changing_global_fonts(review):
    module, period = review
    from matplotlib import rcParams

    previous_fonts = list(rcParams["font.family"])
    empty = module.build_review([], {}, period.end, period, 456)
    partial = module.build_review([record(1, period.start, 0, 1, boss=2, lap=10)], {},
                                 period.end, period, 456)
    assert partial["stage"] == "C" and len(partial["samples"]) == 1
    images = [module.render_review(empty, page) for page in module.REVIEW_PAGES]
    images.append(module.render_review(partial, "distribution"))
    images.append(module.render_review(partial, "ranges"))
    for message in images:
        encoded, = re.findall(r"base64://([A-Za-z0-9+/=]+)", message)
        image = Image.open(io.BytesIO(base64.b64decode(encoded)))
        assert image.width == 1440 and image.getpixel((0, 0)) == (23, 43, 77)
    assert list(rcParams["font.family"]) == previous_fonts
