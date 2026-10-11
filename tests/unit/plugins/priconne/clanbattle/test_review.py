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


def record(uid, moment, damage, log, boss=1, lap=23, flag=0):
    return dict(pcrid=uid, name=f"成员{uid}", time=moment, damage=damage,
                battle_log_id=log, boss=str(boss), lap=lap, flag=flag)


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


def test_member_ranges_use_unrounded_same_boss_stage_full_medians(review):
    module, period = review
    rows = [record(1, period.start, 299_999_999, 1), record(2, period.start, 300_000_000, 2),
            record(3, period.start, 310_000_000, 3), record(3, period.start, 330_000_000, 4),
            record(4, period.start, 350_000_000, 5),
            record(3, period.start, 9_000_000_000, 6, flag=.5),
            record(3, period.start, 9_000_000_000, 7, lap=10),
            record(1, period.start, 400_000_000, 8, boss=2)]
    data = module.build_review(rows, {}, period.end, period, 456)
    groups = module.damage_ranges(data)
    assert data["stage"] == "D"
    assert groups[0, 1] == [("1", 299_999_999, 1)]
    assert groups[1, 1] == [("2", 300_000_000, 1)]
    assert groups[2, 1] == [("3", 320_000_000, 2)]
    assert groups[3, 1] == [("4", 350_000_000, 1)]
    assert groups[3, 2] == [("1", 400_000_000, 1)]
    assert sum(len(entries) for entries in groups.values()) == 5


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
    for message in images:
        encoded, = re.findall(r"base64://([A-Za-z0-9+/=]+)", message)
        image = Image.open(io.BytesIO(base64.b64decode(encoded)))
        assert image.width == 1440 and image.getpixel((0, 0)) == (23, 43, 77)
    assert list(rcParams["font.family"]) == previous_fonts
