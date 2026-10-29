import pytest


@pytest.fixture(autouse=True)
def battle_schedule(app, monkeypatch):
    from src.plugins.priconne import clanbattle
    from src.plugins.priconne.clanbattle.period import BattlePeriod

    start = int((clanbattle.pcr_date(clanbattle.time.time()) - clanbattle.timedelta(days=2)).timestamp())
    period = BattlePeriod(42, start, start + 5 * 86400 - 5 * 3600)

    async def schedule(*args, **kwargs):
        return period

    async def config(path):
        return {"clan_battle_id": 42}

    monkeypatch.setattr(clanbattle, "get_period", schedule)
    monkeypatch.setattr(clanbattle, "load_config", config)
    # 报表测试使用显式快照，不让启动恢复任务覆盖这些状态。
    monkeypatch.setattr(clanbattle, "_resumed", True)
    return period


async def test_ended_event_keeps_same_period_reference_and_never_reads_live_queues(
    current_battle, battle_schedule, app, monkeypatch,
):
    clanbattle, compat, now = current_battle
    from src.plugins.priconne.clanbattle import reports

    sent, tables, ranges = [], [], []
    monkeypatch.setattr(clanbattle.time, "time", lambda: battle_schedule.end)

    async def send(self, event, message, **kwargs):
        sent.append(str(message))

    class Records:
        def __init__(self, group_id):
            pass

        async def get_report_records(self, start, end):
            ranges.append((start, end))
            return []

    def unexpected_queue(*args, **kwargs):
        raise AssertionError("活动结束后不读取现场队列")

    monkeypatch.setattr(compat.LegacyBot, "send", send)
    monkeypatch.setattr(clanbattle, "RecordDao", Records)
    monkeypatch.setattr(clanbattle, "ApplyDao", unexpected_queue)
    monkeypatch.setattr(reports, "_report_image", lambda title, metadata, cards, sections, note: tables.append(sections[0][2]) or "表格")
    async with app.test_matcher(_legacy_matcher(clanbattle.command_center)) as ctx:
        bot = ctx.create_bot(base=Bot, adapter=ctx.create_adapter(base=Adapter), self_id="10000")
        ctx.receive_event(bot, _group_event("会战指挥台", 204))
    assert ranges == [(battle_schedule.start, battle_schedule.end)]
    assert "已结束" in sent[0] and "整期15刀" in sent[0] and "近7" not in sent[0]
    assert all("申未知" in row[2] and row[4:7] == ["—", "待确认", "—"] for row in tables[0])
import json
from types import SimpleNamespace
from nonebot.adapters.onebot.v11 import Adapter, Bot, PrivateMessageEvent, Message, MessageSegment
from nonebot.matcher import matchers

from tests.nonebot.test_arcade_queries import _group_event


def _legacy_matcher(func):
    candidates = [
        matcher for group in matchers.values() for matcher in group
        if any(any(cell.cell_contents is func for cell in (handler.call.__closure__ or ()))
               for handler in matcher.handlers)
    ]
    assert len(candidates) == 1
    return candidates[0]


async def test_current_battle_report_sends_verified_damage_and_marks_missing_part(app, monkeypatch):
    from src.plugins.priconne import clanbattle, compat

    records = [dict(pcrid=1, name="成员", lap=42, boss="1", flag=1, damage=500, effective_damage=100),
               dict(pcrid=1, name="成员", lap=42, boss="2", flag=None, damage=700, effective_damage=None)]
    sent, rendered = [], []
    original = clanbattle.get_cbreport

    class Records:
        def __init__(self, group_id, period):
            assert group_id == 456 and period.id == 42

        async def get_all_records(self):
            return records

        async def get_max_dao(self):
            return 9

    async def render(*args):
        rendered.append(args)
        return await original(*args)

    async def send(self, event, message, **kwargs):
        sent.append(str(message))

    monkeypatch.setattr(clanbattle, "RecordDao", Records)
    monkeypatch.setattr(clanbattle, "get_cbreport", render)
    monkeypatch.setattr(compat.LegacyBot, "send", send)
    async with app.test_matcher(_legacy_matcher(clanbattle.get_report)) as ctx:
        bot = ctx.create_bot(base=Bot, adapter=ctx.create_adapter(base=Adapter), self_id="10000")
        ctx.receive_event(bot, _group_event("当前战报", 701))
    assert rendered[0][1:] == (100, 450)
    assert "1条实际扣血待核验" in sent[0] and "[CQ:image" in sent[0]
    assert records[0]["damage"] == 500 and records[1]["damage"] == 700


@pytest.mark.parametrize(("command", "handler"), [("预约表", "formsubscribe"), ("查树", "tree_list")])
async def test_registration_queries_send_images_and_keep_member_lookup_failure_safe(
    current_battle, battle_schedule, app, monkeypatch, command, handler,
):
    import base64
    import io
    from PIL import Image
    from src.plugins.priconne.clanbattle import reports

    clanbattle, compat, now = current_battle
    sent, rendered, looked_up = [], [], []
    original_render = reports._report_image

    def render(*args):
        rendered.append(args)
        return original_render(*args)

    class Queues:
        def __init__(self, group_id):
            assert group_id == 456

        async def get_subscriber(self, order):
            return [(123, 29, "[CQ:at,qq=all]")] if order == 3 else []

        async def get_tree(self, order):
            return [(123, now - 60, "[CQ:at,qq=all]"), (999, battle_schedule.start - 1, "上期"),
                    (888, now + 1, "未来")] if order == 5 else []

    async def member(self, **kwargs):
        looked_up.append(kwargs["user_id"])
        raise RuntimeError("member lookup failed")

    async def send(self, event, message, **kwargs):
        sent.append(message)

    monkeypatch.setattr(clanbattle.time, "time", lambda: now)
    monkeypatch.setattr(clanbattle, "SubscribeDao", Queues)
    monkeypatch.setattr(clanbattle, "TreeDao", Queues)
    monkeypatch.setattr(reports, "_report_image", render)
    monkeypatch.setattr(compat.LegacyBot, "get_group_member_info", member)
    monkeypatch.setattr(compat.LegacyBot, "send", send)
    async with app.test_matcher(_legacy_matcher(getattr(clanbattle, handler))) as ctx:
        bot = ctx.create_bot(base=Bot, adapter=ctx.create_adapter(base=Adapter), self_id="10000")
        ctx.receive_event(bot, _group_event(command, 510))
    assert looked_up == [123] and len(sent) == 1
    assert sent[0].startswith("[CQ:image,file=base64://") and "[CQ:at" not in sent[0]
    image = Image.open(io.BytesIO(base64.b64decode(sent[0].split("base64://")[1].split("]")[0])))
    assert image.width == 1440 and image.getpixel((0, 0)) == (23, 43, 77)
    rows = rendered[0][3][0][2]
    assert len(rows) == 1 and "QQ 123" in rows[0][1] and rows[0][0] == ("3王" if command == "预约表" else "5王")
    assert "[CQ:at,qq=all]" in str(rows)
    if command == "预约表":
        assert "已过周目" in rows[0][-1]


@pytest.mark.parametrize("command", ["预约表", "查树"])
@pytest.mark.parametrize("condition", ["ended", "unbound"])
async def test_registration_queries_do_not_read_old_period_data(
    current_battle, battle_schedule, app, monkeypatch, command, condition,
):
    from src.plugins.priconne.clanbattle import reports

    clanbattle, compat, now = current_battle
    captured, sent = [], []

    def forbidden(*args, **kwargs):
        raise AssertionError("不能读取旧期登记")

    async def old_config(path):
        return {"clan_battle_id": 41}

    async def send(self, event, message, **kwargs):
        sent.append(message)

    if condition == "unbound":
        monkeypatch.setattr(clanbattle, "load_config", old_config)
    monkeypatch.setattr(clanbattle.time, "time", lambda: battle_schedule.end if condition == "ended" else now)
    monkeypatch.setattr(clanbattle, "SubscribeDao", forbidden)
    monkeypatch.setattr(clanbattle, "TreeDao", forbidden)
    monkeypatch.setattr(compat.LegacyBot, "send", send)
    monkeypatch.setattr(reports, "_report_image", lambda *args: captured.append(args) or "[CQ:image,file=test.png]")
    handler = clanbattle.formsubscribe if command == "预约表" else clanbattle.tree_list
    async with app.test_matcher(_legacy_matcher(handler)) as ctx:
        bot = ctx.create_bot(base=Bot, adapter=ctx.create_adapter(base=Adapter), self_id="10000")
        ctx.receive_event(bot, _group_event(command, 511))
    assert sent == ["[CQ:image,file=test.png]"]
    assert ("会战复盘" if condition == "ended" else "绑定本期") in str(captured)


async def test_reservation_query_rechecks_period_binding_after_member_lookup(current_battle, app, monkeypatch):
    from src.plugins.priconne.clanbattle import reports

    clanbattle, compat, now = current_battle
    binding, captured = [42], []

    async def config(path):
        return {"clan_battle_id": binding[0]}

    class Queues:
        def __init__(self, group_id):
            pass

        async def get_subscriber(self, order):
            return [(123, 30, "过渡中的旧登记")] if order == 1 else []

    async def member(self, **kwargs):
        binding[0] = 43
        return {"nickname": "成员"}

    async def send(self, event, message, **kwargs):
        pass

    monkeypatch.setattr(clanbattle.time, "time", lambda: now)
    monkeypatch.setattr(clanbattle, "load_config", config)
    monkeypatch.setattr(clanbattle, "SubscribeDao", Queues)
    monkeypatch.setattr(compat.LegacyBot, "get_group_member_info", member)
    monkeypatch.setattr(compat.LegacyBot, "send", send)
    monkeypatch.setattr(reports, "_report_image", lambda *args: captured.append(args) or "[CQ:image,file=test.png]")
    async with app.test_matcher(_legacy_matcher(clanbattle.formsubscribe)) as ctx:
        bot = ctx.create_bot(base=Bot, adapter=ctx.create_adapter(base=Adapter), self_id="10000")
        ctx.receive_event(bot, _group_event("预约表", 512))
    assert "过渡中的旧登记" not in str(captured) and "绑定本期" in str(captured)


@pytest.mark.parametrize(("command", "pages"), [
    ("会战复盘", ["overview", "members", "bosses", "distribution", "ranges"]),
    ("会战总结", ["overview", "members", "bosses", "distribution", "ranges"]),
    ("刀伤分布", ["distribution"]), ("刀伤分档", ["ranges"]),
])
async def test_review_commands_load_and_send_scoped_pages(app, battle_schedule, monkeypatch, command, pages):
    from src.plugins.priconne import clanbattle, compat

    sent, rendered, ranges = [], [], []

    async def send(self, event, message, **kwargs):
        sent.append(str(message))

    class Records:
        def __init__(self, group_id):
            assert group_id == 456

        async def get_report_records(self, start, end):
            ranges.append((start, end))
            return []

    def render(data, page):
        assert data["period"].id == 42 and data["group_id"] == 456
        rendered.append(page)
        return "图片:" + page

    monkeypatch.setattr(clanbattle.time, "time", lambda: battle_schedule.end)
    monkeypatch.setattr(clanbattle, "run_group", {})
    monkeypatch.setattr(clanbattle, "clanbattle_info", {})
    monkeypatch.setattr(clanbattle, "RecordDao", Records)
    monkeypatch.setattr(clanbattle, "render_review", render)
    monkeypatch.setattr(compat.LegacyBot, "send", send)
    async with app.test_matcher(_legacy_matcher(clanbattle.battle_review)) as ctx:
        bot = ctx.create_bot(base=Bot, adapter=ctx.create_adapter(base=Adapter), self_id="10000")
        ctx.receive_event(bot, _group_event(command, 404))
    assert ranges == [(battle_schedule.start, battle_schedule.end)]
    assert rendered == pages and len(sent) == len(pages)
    assert "第42期会战复盘" in sent[0]


@pytest.mark.parametrize(("command", "handler", "expected"), [
    ("今日刀表", "today_state", "今日出刀分布"),
    ("今日出刀", "today_state", "今日出刀分布"),
    ("出刀时段", "time_preference", "成员出刀时段偏好"),
])
async def test_report_commands_render_roster_even_without_records(app, monkeypatch, command, handler, expected):
    from src.plugins.priconne import clanbattle
    from src.plugins.priconne import compat
    from src.plugins.priconne.clanbattle import reports

    sent, tables, ranges = [], [], []
    titles, notes = [], []
    original_render = reports._report_image

    def render(title, metadata, cards, sections, note):
        titles.append(title)
        notes.append(note)
        tables.append(sections[0][2])
        return original_render(title, metadata, cards, sections, note)

    async def send(self, event, message, **kwargs):
        sent.append(str(message))

    async def config(path):
        return {"member_by_id": {"1": "同名", "2": "同名"}}

    class Records:
        def __init__(self, group_id):
            assert group_id == 456

        async def get_report_records(self, start, end):
            ranges.append((start, end))
            return []

    monkeypatch.setattr(compat.LegacyBot, "send", send)
    monkeypatch.setattr(clanbattle, "load_config", config)
    monkeypatch.setattr(clanbattle, "RecordDao", Records)
    monkeypatch.setattr(clanbattle, "run_group", {})
    monkeypatch.setattr(clanbattle, "clanbattle_info", {})
    monkeypatch.setattr(reports, "_report_image", render)
    async with app.test_matcher(_legacy_matcher(getattr(clanbattle, handler))) as ctx:
        bot = ctx.create_bot(base=Bot, adapter=ctx.create_adapter(base=Adapter), self_id="10000")
        ctx.receive_event(bot, _group_event(command, 91))
    assert len(sent) == 1 and expected == titles[0] and "[CQ:image" in sent[0]
    if handler == "today_state":
        assert sent[0].startswith("[CQ:image") and "监控离线" in notes[0]
        assert tables[0][0][1]["items"] == ["同名 (1)", "同名 (2)"] and tables[0][0][2] == 2
    else:
        assert "战绩同步状态待核验" in sent[0] and len(tables[0]) == 2
    assert ranges[0][0] < ranges[0][1]


async def test_command_center_excludes_old_event_snapshot(app, monkeypatch):
    from src.plugins.priconne import clanbattle, compat

    sent = []

    async def send(self, event, message, **kwargs):
        sent.append(message)

    async def config(path):
        return {"456": {"snapshot": {"time": 1, "rank": 42, "boss": "旧周目进度"}}}

    class Records:
        def __init__(self, group_id):
            assert group_id == 456

        async def get_report_records(self, start, end):
            assert start == (await clanbattle.get_period()).start
            return []

    monkeypatch.setattr(clanbattle, "RecordDao", Records)
    monkeypatch.setattr(compat.LegacyBot, "send", send)
    monkeypatch.setattr(clanbattle, "load_config", config)
    monkeypatch.setattr(clanbattle, "run_group", {})
    monkeypatch.setattr(clanbattle, "clanbattle_info", {})
    async with app.test_matcher(_legacy_matcher(clanbattle.command_center)) as ctx:
        bot = ctx.create_bot(base=Bot, adapter=ctx.create_adapter(base=Adapter), self_id="10000")
        ctx.receive_event(bot, _group_event("会战指挥台", 92))
    assert len(sent) == 1 and sent[0].type == "text"
    assert "旧周目进度" not in str(sent[0]) and "缺少结构化状态" in str(sent[0])


async def test_command_center_renders_current_queues_and_keeps_cq_comments_as_text(app, monkeypatch):
    from src.plugins.priconne import clanbattle, compat
    from src.plugins.priconne.clanbattle import reports

    now = int(clanbattle.time.time())
    bosses = [{"order": order, "lap_num": 30, "stage": "D", "current_hp": 100,
               "max_hp": 200, "available": True, "fighter_num": 0} for order in range(1, 6)]
    sent, tables = [], []

    async def send(self, event, message, **kwargs):
        sent.append(message)

    async def member(self, **kwargs):
        assert kwargs == {"group_id": 456, "user_id": 789}
        return {"card": "申请成员"}

    class Queues:
        def __init__(self, group_id):
            assert group_id == 456

        async def get_apply(self, order):
            return [(789, now - 300, "[CQ:at,qq=all]")] if order == 1 else []

        async def get_subscriber(self, order):
            return [(789, 31, "下一周目")] if order == 1 else []

        async def get_tree(self, order):
            return []

    snapshot = {"time": now, "rank": 42, "boss": "当前进度", "bosses": bosses,
                "records_synced_at": now, "record_sync_ok": True}
    monkeypatch.setattr(clanbattle, "run_group", {456: {"snapshot": snapshot}})
    monkeypatch.setattr(clanbattle, "clanbattle_info", {456: SimpleNamespace(loop_check=now)})
    monkeypatch.setattr(compat.LegacyBot, "send", send)
    monkeypatch.setattr(compat.LegacyBot, "get_group_member_info", member)
    class Records:
        def __init__(self, group_id):
            assert group_id == 456

        async def get_report_records(self, start, end):
            return []

    monkeypatch.setattr(clanbattle, "RecordDao", Records)
    for dao in ("ApplyDao", "SubscribeDao", "TreeDao"):
        monkeypatch.setattr(clanbattle, dao, Queues)
    monkeypatch.setattr(reports, "_report_image", lambda title, metadata, cards, sections, note: tables.append(sections[0][2]) or "表格")
    async with app.test_matcher(_legacy_matcher(clanbattle.command_center)) as ctx:
        bot = ctx.create_bot(base=Bot, adapter=ctx.create_adapter(base=Adapter), self_id="10000")
        ctx.receive_event(bot, _group_event("会战指挥台", 94))
    assert len(sent) == 2 and "监控：在线" in sent[0]
    assert len(tables) == 1 and tables[0][0][2] == "战0 申1 约0/1 树0"
    assert sent[1].type == "text" and "[CQ:at,qq=all]" in sent[1].data["text"]
    assert "申请成员" in sent[1].data["text"] and "暂无人挑战" in sent[1].data["text"]


@pytest.mark.parametrize(("command", "handler"), [
    ("出刀时段", "time_preference"), ("会战指挥台", "command_center"), ("BOSS推进参考", "command_center"),
    ("剩余补偿", "query_carry_inventory"),
])
async def test_private_report_does_not_read_group_data(app, monkeypatch, command, handler):
    from src.plugins.priconne import clanbattle, compat

    sent = []

    async def send(self, event, message, **kwargs):
        sent.append(str(message))

    def unexpected_read(*args):
        pytest.fail("私聊不应查询公会数据")

    monkeypatch.setattr(compat.LegacyBot, "send", send)
    monkeypatch.setattr(clanbattle, "RecordDao", unexpected_read)
    monkeypatch.setattr(clanbattle, "ApplyDao", unexpected_read)
    monkeypatch.setattr(clanbattle, "TreeDao", unexpected_read)
    async with app.test_matcher(_legacy_matcher(getattr(clanbattle, handler))) as ctx:
        bot = ctx.create_bot(base=Bot, adapter=ctx.create_adapter(base=Adapter), self_id="10000")
        event = PrivateMessageEvent(time=1, self_id=10000, post_type="message", sub_type="friend",
                                    user_id=123, message_type="private", message_id=93,
                                    message=Message(command), raw_message=command, font=0,
                                    sender={"user_id": 123, "nickname": "tester"})
        ctx.receive_event(bot, event)
    assert len(sent) == 1 and "请在公会群中查询" in sent[0]


@pytest.fixture()
def current_battle(app, monkeypatch):
    from src.plugins.priconne import clanbattle, compat

    now = int(clanbattle.time.time())
    bosses = [{"order": order, "lap_num": 30, "stage": "D", "current_hp": 15000000,
               "max_hp": 20000000, "available": True, "fighter_num": 0} for order in range(1, 6)]
    snapshot = {"time": now, "clan_battle_id": 42, "rank": 10, "boss": "当前状态", "bosses": bosses,
                "records_synced_at": now, "record_sync_ok": True}
    monkeypatch.setattr(clanbattle, "run_group", {456: {"snapshot": snapshot}})
    monkeypatch.setattr(clanbattle, "clanbattle_info", {456: SimpleNamespace(loop_check=now)})
    return clanbattle, compat, now


@pytest.mark.parametrize("command", ["状态", "boss状态"])
async def test_status_matchers_send_image_and_keep_each_boss_count_and_name_fallback(
    current_battle, battle_schedule, app, monkeypatch, command,
):
    import base64
    import io
    from PIL import Image
    from src.plugins.priconne.clanbattle import reports

    clanbattle, compat, now = current_battle
    clanbattle.clanbattle_info[456].event = battle_schedule
    clanbattle.clanbattle_info[456].qq_id = 777
    clanbattle.run_group[456]["snapshot"]["bosses"][1]["fighter_num"] = 2
    sent, rendered = [], []
    original_render = reports._report_image

    def render(title, metadata, cards, sections, note):
        rendered.append(sections)
        return original_render(title, metadata, cards, sections, note)

    class Queues:
        def __init__(self, group_id):
            assert group_id == 456

        async def get_apply(self, order):
            return [(uid, now - 10, "[CQ:at,qq=all]") for uid in (123, 456, 789)] if order == 1 else []

        async def get_tree(self, order):
            return [(789, now - 20, "等待")] if order == 3 else []

    class Records:
        def __init__(self, group_id):
            assert group_id == 456

        async def get_report_records(self, start, end):
            assert start == battle_schedule.start and end <= battle_schedule.end
            return [dict(pcrid=index % 2, name="成员", time=now - 60, lap=30, boss="1",
                         flag=0, damage=20000000, battle_log_id=index + 1) for index in range(5)]

    async def member(self, **kwargs):
        raise RuntimeError("member lookup failed")

    async def send(self, event, message, **kwargs):
        sent.append(message)

    monkeypatch.setattr(clanbattle.time, "time", lambda: now)
    monkeypatch.setattr(clanbattle, "ApplyDao", Queues)
    monkeypatch.setattr(clanbattle, "TreeDao", Queues)
    monkeypatch.setattr(clanbattle, "RecordDao", Records)
    monkeypatch.setattr(reports, "_report_image", render)
    monkeypatch.setattr(compat.LegacyBot, "get_group_member_info", member)
    monkeypatch.setattr(compat.LegacyBot, "send", send)
    handler = clanbattle.daostate if command == "状态" else clanbattle.bosstate
    async with app.test_matcher(_legacy_matcher(handler)) as ctx:
        bot = ctx.create_bot(base=Bot, adapter=ctx.create_adapter(base=Adapter), self_id="10000")
        ctx.receive_event(bot, _group_event(command, 410))
    assert len(sent) == 1 and sent[0].startswith("[CQ:image,file=base64://")
    image = Image.open(io.BytesIO(base64.b64decode(sent[0].split("base64://")[1].split("]")[0])))
    assert image.width == 1440 and image.getpixel((0, 0)) == (23, 43, 77)
    rows = rendered[0][1][2]
    assert rows[0][3:6] == [0, 3, 0] and rows[1][3:6] == [2, 0, 0]
    assert rendered[0][0][2][0][0] == "QQ 777" and rows[0][1]["zone"] == "烂尾"
    if command == "boss状态":
        assert "QQ 123" in str(rendered) and "[CQ:at,qq=all]" in str(rendered)


@pytest.mark.parametrize("foreign", [False, True])
async def test_stopped_status_restores_last_monitor_but_never_leaks_other_period_identity(
    current_battle, app, monkeypatch, foreign,
):
    from src.plugins.priconne.clanbattle import reports

    clanbattle, compat, now = current_battle
    clanbattle.run_group[456]["snapshot"].update(monitor_qq_id=777, clan_battle_id=41 if foreign else 42)
    clanbattle._set_monitor_stopped(456)
    clanbattle._restore_run_group(json.loads(json.dumps(clanbattle.run_group)))
    monkeypatch.setattr(clanbattle, "clanbattle_info", {})
    captured, requested, sent = [], [], []

    async def member(self, **kwargs):
        requested.append(kwargs["user_id"])
        return {"card": "演示监控人"}

    async def send(self, event, message, **kwargs):
        sent.append(message)

    def no_records(*args, **kwargs):
        raise AssertionError("离线状态不得查询实时样本或登记")

    monkeypatch.setattr(clanbattle.time, "time", lambda: now)
    monkeypatch.setattr(clanbattle, "RecordDao", no_records)
    monkeypatch.setattr(compat.LegacyBot, "get_group_member_info", member)
    monkeypatch.setattr(compat.LegacyBot, "send", send)
    monkeypatch.setattr(reports, "_report_image", lambda *args: captured.append(args) or "[CQ:image,file=test.png]")
    async with app.test_matcher(_legacy_matcher(clanbattle.daostate)) as ctx:
        bot = ctx.create_bot(base=Bot, adapter=ctx.create_adapter(base=Adapter), self_id="10000")
        ctx.receive_event(bot, _group_event("状态", 712))
    assert sent == ["[CQ:image,file=test.png]"]
    monitor = captured[0][3][0]
    assert monitor[1][0] == "上次监控人"
    assert requested == ([] if foreign else [777])
    assert monitor[2][0][0] == ("未知" if foreign else "演示监控人 (QQ 777)")


@pytest.mark.parametrize("condition", ["expired", "ended", "foreign"])
async def test_status_query_never_reads_unavailable_period_queues(
    current_battle, battle_schedule, app, monkeypatch, condition,
):
    from src.plugins.priconne.clanbattle import reports

    clanbattle, compat, moment = current_battle
    clanbattle.clanbattle_info[456].event = battle_schedule
    now = battle_schedule.end if condition == "ended" else moment + 121 if condition == "expired" else moment
    if condition == "foreign":
        clanbattle.run_group[456]["snapshot"]["clan_battle_id"] = 41
    sent, captured = [], []

    def forbidden(*args, **kwargs):
        raise AssertionError("不得读取过期或其他期现场登记")

    async def send(self, event, message, **kwargs):
        sent.append(message)

    monkeypatch.setattr(clanbattle.time, "time", lambda: now)
    monkeypatch.setattr(clanbattle, "ApplyDao", forbidden)
    monkeypatch.setattr(clanbattle, "TreeDao", forbidden)
    monkeypatch.setattr(compat.LegacyBot, "send", send)
    monkeypatch.setattr(reports, "_report_image", lambda title, metadata, cards, sections, note: captured.append(sections) or "[CQ:image,file=test.png]")
    async with app.test_matcher(_legacy_matcher(clanbattle.bosstate)) as ctx:
        bot = ctx.create_bot(base=Bot, adapter=ctx.create_adapter(base=Adapter), self_id="10000")
        ctx.receive_event(bot, _group_event("boss状态", 411))
    assert sent == ["[CQ:image,file=test.png]"]
    assert "申请与挂树" not in str(captured)
    if condition == "ended":
        assert "会战复盘" in str(captured) and "出刀监控" not in str(captured)


async def test_application_saves_target_binding_and_keeps_comment_as_plain_text(current_battle, app, monkeypatch):
    clanbattle, compat, _ = current_battle
    from src.plugins.priconne.clanbattle import reports

    saved, sent = [], []

    class Applications:
        def __init__(self, group_id):
            assert group_id == 456

        async def add_apply(self, uid, boss, text):
            saved.append((uid, boss, text))
            return 1

    async def send(self, event, message, **kwargs):
        sent.append(message)

    monkeypatch.setattr(clanbattle, "ApplyDao", Applications)
    monkeypatch.setattr(compat.LegacyBot, "send", send)
    async with app.test_matcher(_legacy_matcher(clanbattle.apply)) as ctx:
        bot = ctx.create_bot(base=Bot, adapter=ctx.create_adapter(base=Adapter), self_id="10000")
        text = "申请出刀 3 补偿60秒 450万 [CQ:at,qq=all]"
        event = _group_event(text, 201)
        event.message = Message(MessageSegment.text(text))
        ctx.receive_event(bot, event)
    assert saved[0][:2] == (123, 3)
    declaration = reports.decode_declaration(saved[0][2])
    assert declaration == {"kind": "comp", "seconds": 60, "damage": 4500000, "note": "[CQ:at,qq=all]",
                           "event": 42, "lap": 30, "hp": 15000000}
    assert sent[0].type == "text" and "补偿60秒" in str(sent[0])
    assert "[CQ:at,qq=all]" in sent[0].data["text"]


@pytest.mark.parametrize(("command", "saved_expected"), [
    ("申请出刀 3 请等我 十分钟", "请等我 十分钟"),
    ("申请出刀 3 完整 1000万", None), ("申请出刀 3 完整 0万", None),
])
async def test_offline_legacy_application_works_but_damage_declaration_requires_current_state(
    current_battle, app, monkeypatch, command, saved_expected,
):
    clanbattle, compat, _ = current_battle
    saved, sent = [], []
    monkeypatch.setattr(clanbattle, "clanbattle_info", {})

    class Applications:
        def __init__(self, group_id):
            pass

        async def add_apply(self, uid, boss, text):
            saved.append(text)
            return 1

    async def send(self, event, message, **kwargs):
        sent.append(str(message))

    monkeypatch.setattr(clanbattle, "ApplyDao", Applications)
    monkeypatch.setattr(compat.LegacyBot, "send", send)
    async with app.test_matcher(_legacy_matcher(clanbattle.apply)) as ctx:
        bot = ctx.create_bot(base=Bot, adapter=ctx.create_adapter(base=Adapter), self_id="10000")
        ctx.receive_event(bot, _group_event(command, 202))
    assert saved == ([] if saved_expected is None else [saved_expected])
    assert len(sent) == 1
    if saved_expected is not None:
        assert "申请成功" in sent[0]
    elif " 完整 0万" in command:
        assert "正整数" in sent[0]
    else:
        assert "最新会战状态" in sent[0]


@pytest.mark.parametrize(("command", "state_changed"), [
    ("会战指挥台", False), ("BOSS推进参考", False), ("boss推进参考", False),
    ("会战指挥台", True),
])
async def test_unified_command_center_uses_declarations_and_rechecks_snapshot(
    current_battle, app, monkeypatch, command, state_changed,
):
    clanbattle, compat, now = current_battle
    from src.plugins.priconne.clanbattle import reports

    sent, tables, ranges = [], [], []

    async def send(self, event, message, **kwargs):
        sent.append(message)

    async def member(self, **kwargs):
        if state_changed:
            snapshot = clanbattle.run_group[456]["snapshot"]
            bosses = [dict(boss, current_hp=14000000 if boss["order"] == 3 else boss["current_hp"])
                      for boss in snapshot["bosses"]]
            clanbattle.run_group[456] = {"snapshot": dict(snapshot, bosses=bosses)}
        return {"card": "成员甲" if kwargs["user_id"] == 123 else "成员乙"}

    class Queues:
        def __init__(self, group_id):
            assert group_id == 456

        async def get_apply(self, order):
            if order != 3:
                return []
            return [(uid, now - 10, "[出刀申报]" + json.dumps({
                "event": 42, "lap": 30, "hp": 15000000, "kind": "full", "seconds": 90,
                "damage": damage, "note": "[CQ:at,qq=all]"}, ensure_ascii=False))
                    for uid, damage in ((123, 10000000), (789, 8000000))]

        async def get_tree(self, order):
            return []

        async def get_subscriber(self, order):
            return []

    class Records:
        def __init__(self, group_id):
            assert group_id == 456

        async def get_report_records(self, start, end):
            ranges.append((start, end))
            return [{"pcrid": i % 2 + 1, "name": "成员", "time": now - i * 60, "lap": 30,
                     "boss": "3", "flag": 0, "damage": 10000000, "battle_log_id": i + 1} for i in range(5)]

    monkeypatch.setattr(compat.LegacyBot, "send", send)
    monkeypatch.setattr(compat.LegacyBot, "get_group_member_info", member)
    monkeypatch.setattr(clanbattle, "RecordDao", Records)
    monkeypatch.setattr(clanbattle, "ApplyDao", Queues)
    monkeypatch.setattr(clanbattle, "TreeDao", Queues)
    monkeypatch.setattr(clanbattle, "SubscribeDao", Queues)
    monkeypatch.setattr(reports, "_report_image", lambda title, metadata, cards, sections, note: tables.append(sections[0][2]) or "表格")
    async with app.test_matcher(_legacy_matcher(clanbattle.command_center)) as ctx:
        bot = ctx.create_bot(base=Bot, adapter=ctx.create_adapter(base=Adapter), self_id="10000")
        ctx.receive_event(bot, _group_event(command, 203))
    assert len(sent) == 2 and sent[1].type == "text"
    assert "[CQ:at,qq=all]" in sent[1].data["text"] and "[出刀申报]" not in sent[1].data["text"]
    assert len(tables) == 1 and "会战指挥台" in str(sent[0])
    assert ranges[0][0] == (await clanbattle.get_period()).start
    if state_changed:
        assert "1400万" in tables[0][2][1]
        assert tables[0][2][5:7] == ["0人/0", "1400万"]
        assert "血量已变化" in sent[1].data["text"]
    else:
        assert tables[0][2][4:7] == ["2/2", "2人/1800万", 0]


@pytest.mark.parametrize(('command', 'initial', 'role', 'mention', 'expected', 'reason'), [
    ('登记会战成员 1', {}, 'member', None, {'123': '1'}, '已登记'),
    ('登记会战成员 2', {'123': '1'}, 'member', None, None, '先【取消'),
    ('登记会战成员 1', {'789': '1'}, 'member', None, None, '其他QQ'),
    ('登记会战成员 99', {}, 'member', None, None, '不在当前群名册'),
    ('登记会战成员 1', {}, 'member', 789, None, '群管理员权限'),
    ('登记会战成员 1', {}, 'admin', 789, {'789': '1'}, '已登记'),
    ('取消会战成员登记', {'123': '1', '789': '2'}, 'member', None, {'789': '2'}, '已取消'),
    ('取消会战成员登记', {'123': '1', '789': '2'}, 'owner', 789, {'123': '1'}, '已取消'),
    ('登记会战成员 1', {}, 'admin', 'all', None, '不能@全体'),
    ('登记会战成员 1', [], 'member', None, None, '无法读取'),
])
async def test_member_registration_permissions_and_identity_uniqueness(
    app, monkeypatch, command, initial, role, mention, expected, reason,
):
    from src.plugins.priconne import clanbattle, compat

    sent, saved, renamed = [], [], []
    roster = {'member_by_id': {'1': '同名', '2': '同名'}, 'clan_battle_id': 42}

    async def read(path):
        return initial if path.endswith('member_links.json') else roster

    async def write(path, value):
        assert path.endswith('456' + clanbattle.os.sep + 'member_links.json.tmp')
        saved.append(value)

    async def send(self, event, message, **kwargs):
        sent.append(str(message))

    monkeypatch.setattr(clanbattle, 'load_config', read)
    monkeypatch.setattr(clanbattle, 'write_config', write)
    monkeypatch.setattr(clanbattle.os, 'replace', lambda source, target: renamed.append((source, target)))
    original_isfile = clanbattle.os.path.isfile
    monkeypatch.setattr(clanbattle.os.path, 'isfile', lambda path:
                        True if path.endswith('member_links.json') and initial == [] else original_isfile(path))
    monkeypatch.setattr(compat.LegacyBot, 'send', send)
    event = _group_event(command, 301)
    event.sender.role = role
    if mention is not None:
        event.message += MessageSegment.at(mention)
    async with app.test_matcher(_legacy_matcher(clanbattle.member_registration)) as ctx:
        bot = ctx.create_bot(base=Bot, adapter=ctx.create_adapter(base=Adapter), self_id='10000')
        ctx.receive_event(bot, event)
    assert saved == ([] if expected is None else [expected])
    assert len(renamed) == (0 if expected is None else 1)
    if renamed:
        assert renamed[0][0] == renamed[0][1] + '.tmp'
    assert len(sent) == 1 and reason in sent[0]
    assert roster == {'member_by_id': {'1': '同名', '2': '同名'}, 'clan_battle_id': 42}


@pytest.mark.parametrize('stale', [False, True])
async def test_dispatch_command_joins_game_ids_and_requires_fresh_record_sync(current_battle, app, monkeypatch, stale):
    clanbattle, compat, now = current_battle
    from src.plugins.priconne.clanbattle import reports

    snapshot = clanbattle.run_group[456]['snapshot']
    snapshot['records_synced_at'] = now - 121 if stale else now
    captured, sent = [], []

    async def read(path):
        if path.endswith('member_links.json'):
            return {'123': '1', '789': '2'}
        return {'clan_battle_id': 42, 'member_by_id': {'1': '同名', '2': '同名'}}

    class Records:
        def __init__(self, group_id):
            pass

        async def get_report_records(self, start, end):
            return []

    class Queues:
        def __init__(self, group_id):
            pass

        async def get_apply(self, order):
            return [(qq, now - 10, '[出刀申报]' + json.dumps(dict(
                event=42, lap=30, hp=15000000, kind='full', seconds=90, damage=10000000, note='')))
                    for qq in (123, 789)] if order == 1 else []

        async def get_subscriber(self, order):
            return []

        async def get_tree(self, order):
            return []

    async def member(self, **kwargs):
        return {'card': '同名'}

    async def send(self, event, message, **kwargs):
        sent.append(str(message))

    monkeypatch.setattr(clanbattle, 'load_config', read)
    monkeypatch.setattr(clanbattle, 'RecordDao', Records)
    for name in ('ApplyDao', 'TreeDao', 'SubscribeDao'):
        monkeypatch.setattr(clanbattle, name, Queues)
    monkeypatch.setattr(clanbattle, 'coordination_reports', lambda data, group: captured.append(data) or '调度附图')
    monkeypatch.setattr(reports, '_report_image', lambda *args: '五王表')
    monkeypatch.setattr(compat.LegacyBot, 'get_group_member_info', member)
    monkeypatch.setattr(compat.LegacyBot, 'send', send)
    async with app.test_matcher(_legacy_matcher(clanbattle.command_center)) as ctx:
        bot = ctx.create_bot(base=Bot, adapter=ctx.create_adapter(base=Adapter), self_id='10000')
        ctx.receive_event(bot, _group_event('会战指挥台', 302))
    assert len(sent) == 2 and '调度附图' in sent[0]
    assert captured[0]['ready'] is not stale
    if stale:
        assert captured[0]['pairs'] == []
    else:
        assert captured[0]['pairs'][0]['gap'] == -5000000
        assert {p['pcrid'] for p in captured[0]['pairs'][0]['members']} == {'1', '2'}


async def test_member_registration_write_failure_preserves_existing_links(app, monkeypatch):
    from src.plugins.priconne import clanbattle, compat

    original, sent, replacements = {'789': '2'}, [], []

    async def read(path):
        return original if path.endswith('member_links.json') else {'member_by_id': {'1': '甲', '2': '乙'}}

    async def write(path, value):
        assert path.endswith('member_links.json.tmp')
        raise OSError('disk full')

    async def send(self, event, message, **kwargs):
        sent.append(str(message))

    monkeypatch.setattr(clanbattle, 'load_config', read)
    monkeypatch.setattr(clanbattle, 'write_config', write)
    monkeypatch.setattr(clanbattle.os, 'replace', lambda *args: replacements.append(args))
    monkeypatch.setattr(compat.LegacyBot, 'send', send)
    async with app.test_matcher(_legacy_matcher(clanbattle.member_registration)) as ctx:
        bot = ctx.create_bot(base=Bot, adapter=ctx.create_adapter(base=Adapter), self_id='10000')
        ctx.receive_event(bot, _group_event('登记会战成员 1', 303))
    assert not replacements and original == {'789': '2'}
    assert len(sent) == 1 and '原登记已保留' in sent[0]

@pytest.mark.parametrize(('command', 'mention', 'target'), [
    ('剩余补偿', None, None), ('查补偿', None, None),
    ('我的补偿', None, '1'), ('查补偿', 789, '2'),
])
async def test_carry_queries_send_real_images_or_scoped_personal_text(
    current_battle, battle_schedule, app, monkeypatch, command, mention, target
):
    clanbattle, compat, now = current_battle
    from src.plugins.priconne.clanbattle import reports
    period = battle_schedule
    config = dict(clan_battle_id=42, member_by_id={'1': '自己', '2': '另一人'},
                  record_coverage=dict(event_id=42, start=period.start, through=now, complete=True))
    records = [dict(pcrid=i, name='记录名', time=now-1, flag=1, carry_inventory=dict(
                   status='ok', reason='', seconds={seconds: (1,1)}, total=(1,1))) for i, seconds in ((1,90),(2,28))]
    sent, ranges = [], []

    async def read(path):
        return {'123': '1', '789': '2'} if path.endswith('member_links.json') else config

    async def send(self, event, message, **kwargs):
        sent.append(str(message))

    class Records:
        def __init__(self, group_id, event):
            assert group_id == 456 and event.id == 42

        async def get_report_records(self, start, end):
            ranges.append((start,end))
            return records

    monkeypatch.setattr(clanbattle, 'load_config', read)
    monkeypatch.setattr(clanbattle, 'RecordDao', Records)
    monkeypatch.setattr(compat.LegacyBot, 'send', send)
    event = _group_event(command, 911)
    if mention is not None:
        event.message += MessageSegment.at(mention)
    async with app.test_matcher(_legacy_matcher(clanbattle.query_carry_inventory)) as ctx:
        bot = ctx.create_bot(base=Bot, adapter=ctx.create_adapter(base=Adapter), self_id='10000')
        ctx.receive_event(bot, event)
    assert len(sent) == 1 and ranges == [(int(clanbattle.pcr_date(now).timestamp()), now+1)]
    if target is None:
        assert sent[0].startswith('[CQ:image')
    else:
        assert '[CQ:image' not in sent[0]
        assert ('自己：90s×1' if target == '1' else '另一人：28s×1') in sent[0]
        assert ('另一人' if target == '1' else '自己') not in sent[0]


@pytest.mark.parametrize('condition', ['unlinked', 'foreign', 'ended', 'at_all'])
async def test_carry_queries_reject_unready_identity_and_period_before_reading_records(
    current_battle, battle_schedule, app, monkeypatch, condition
):
    clanbattle, compat, now = current_battle
    sent = []

    async def read(path):
        if path.endswith('member_links.json'):
            return {}
        return dict(clan_battle_id=41 if condition == 'foreign' else 42, member_by_id={'1':'成员'})

    async def send(self, event, message, **kwargs):
        sent.append(str(message))

    def no_records(*args):
        pytest.fail('invalid identity/period must not query records')

    monkeypatch.setattr(clanbattle, 'load_config', read)
    monkeypatch.setattr(clanbattle, 'RecordDao', no_records)
    monkeypatch.setattr(compat.LegacyBot, 'send', send)
    if condition == 'ended':
        monkeypatch.setattr(clanbattle.time, 'time', lambda: battle_schedule.end)
    event = _group_event('我的补偿' if condition == 'unlinked' else '查补偿', 912)
    if condition == 'at_all':
        event.message += MessageSegment.at('all')
    async with app.test_matcher(_legacy_matcher(clanbattle.query_carry_inventory)) as ctx:
        bot = ctx.create_bot(base=Bot, adapter=ctx.create_adapter(base=Adapter), self_id='10000')
        ctx.receive_event(bot, event)
    expected = dict(unlinked='登记会战成员', foreign='尚未绑定本期', ended='当前没有本期可用补偿', at_all='不能@全体')
    assert len(sent) == 1 and expected[condition] in sent[0]


@pytest.mark.parametrize("command,role,expected", [
    ("关闭播报", "member", None), ("关闭播报", "admin", {"broadcast": False}),
    ("订阅档线", "admin", {"rankline": True}), ("取消档线订阅", "owner", {"rankline": False}),
])
async def test_broadcast_commands_enforce_permissions_and_persist_settings(app, monkeypatch, tmp_path, command, role, expected):
    import json
    from src.plugins.priconne import clanbattle, compat
    monkeypatch.setattr(clanbattle, "clan_path", str(tmp_path))
    monkeypatch.setattr(clanbattle, "_push_settings", None)
    sent = []
    async def send(self, event, message, **kwargs):
        sent.append(str(message))
    monkeypatch.setattr(compat.LegacyBot, "send", send)
    event = _group_event(command, 600)
    event.sender.role = role
    async with app.test_matcher(_legacy_matcher(clanbattle.manage_broadcast)) as ctx:
        bot = ctx.create_bot(base=Bot, adapter=ctx.create_adapter(base=Adapter), self_id="10000")
        ctx.receive_event(bot, event)
    path = tmp_path / "push_settings.json"
    if expected is None:
        assert not path.exists() and "仅群管理员" in sent[0]
    else:
        value = json.loads(path.read_text(encoding="utf-8"))["456"]
        assert value == {**expected, "self_id": "10000"}


@pytest.mark.parametrize("command,valid", [("查档线 50 200", True), ("分数线", True), ("查档线 0", False)])
async def test_rankline_query_matcher_sends_real_image_and_rejects_bad_input(app, battle_schedule, monkeypatch, command, valid):
    from src.plugins.priconne import clanbattle, compat
    sent, calls = [], []
    async def data(path, period, ranks, monitors, gid):
        calls.append((period.id, ranks, gid))
        return {"period_id": 42, "updated_at": period.start, "stale": False, "my": None,
                "lines": [{"rank": 50, "damage": 123450000000, "clan_name": "测试公会"}]}
    async def send(self, event, message, **kwargs):
        sent.append(str(message))
    monkeypatch.setattr(clanbattle, "get_rank_lines", data)
    monkeypatch.setattr(compat.LegacyBot, "send", send)
    async with app.test_matcher(_legacy_matcher(clanbattle.query_rankline)) as ctx:
        bot = ctx.create_bot(base=Bot, adapter=ctx.create_adapter(base=Adapter), self_id="10000")
        ctx.receive_event(bot, _group_event(command, 601))
    assert len(sent) == 1
    if valid:
        assert calls[0][0] == 42 and calls[0][2] == 456
        assert sent[0].startswith("[CQ:image,file=base64://")
    else:
        assert not calls and "名次范围" in sent[0]
