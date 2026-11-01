from datetime import datetime, timedelta, timezone
import pytest

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from tests.integration.test_management_web import console, editors


async def test_correction_uses_private_input_and_independent_before_after(editors):
    from copy import deepcopy
    c = editors
    dao = c.sql.RecordDao(789, c.period)
    async with c.sessions() as session:
        raw, binding = await dao._correction_rows(session)
    original = deepcopy(raw)
    result, _, _, _ = c.sql._prepare_correction(c.period, binding, raw, 2, .5, 1, '核对来源')
    expected_after = deepcopy(original)
    expected_after[1]['settlement'].update(manual_flag=.5, manual_source=1)
    assert raw == original
    assert result['before'] == c.sql.analyse_records(original)
    assert result['after'] == c.sql.analyse_records(expected_after)
    assert 'manual_flag' not in result['before'][1]['settlement']
    assert result['after'][1]['carry_source_id'] == 1
    duplicate = dict(original[1], id=99, settlement={**original[1]['settlement'],
        'report':dict(max_hp=900000000, totals={'123':300000000}, observed_at=1)})
    duplicated = original+[duplicate]
    fingerprint = c.sql._correction_fingerprint(c.period, binding, duplicated)
    duplicate['settlement']['report']['observed_at'] = 100
    assert c.sql.analyse_records(duplicated) == result['before']
    assert c.sql._correction_fingerprint(c.period, binding, duplicated) == fingerprint


async def test_concurrent_corrections_commit_only_once(editors, monkeypatch):
    import asyncio, threading
    from sqlalchemy import select
    from src.plugins.priconne.orm.models import Record
    c = editors
    dao = c.sql.RecordDao(789, c.period)
    operation = dict(source=1, reason='并发核对')
    preview = await dao.correct_record(2, .5, **operation)
    barrier = threading.Barrier(2)
    prepare = c.sql._prepare_correction
    def together(*args):
        result = prepare(*args)
        barrier.wait(timeout=10)
        return result
    monkeypatch.setattr(c.sql, '_prepare_correction', together)
    results = await asyncio.gather(*(dao.correct_record(2, .5, **operation, expected=preview['version'],
        actor=str(actor), commit=True) for actor in (456, 999)), return_exceptions=True)
    assert sum(isinstance(result, dict) and result['saved'] for result in results) == 1, results
    errors = [result for result in results if isinstance(result, Exception)]
    assert len(errors) == 1 and isinstance(errors[0], ValueError)
    async with c.sessions() as session:
        row = (await session.execute(select(Record).where(Record.id == 2))).scalar_one()
        assert row.settlement['correction_revision'] == 1
        assert len(row.settlement['correction_history']) == 1
        assert row.damage == 300000000 and row.remain_time == row.battle_time == 90


async def test_report_queue_batch_preserves_distinct_groups_bosses_and_lap_limit(app, monkeypatch):
    from sqlalchemy import event
    from src.plugins.priconne.clanbattle import sql
    from src.plugins.priconne.orm.models import Apply, Tree, Subscribe
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessions = async_sessionmaker(engine)
    monkeypatch.setattr(sql, "get_session", sessions)
    selects = []
    def count(conn, cursor, statement, parameters, context, many):
        if statement.lstrip().upper().startswith("SELECT"):
            selects.append(statement)
    try:
        async with engine.begin() as connection:
            for model in (Apply, Tree, Subscribe):
                await connection.run_sync(lambda db, model=model: model.__table__.create(db))
        async with sessions() as session:
            for group, boss, text in [(11,1,"先登记"), (11,1,"先登记"), (11,1,"另一留言"),
                                      (11,2,"先登记"), (22,1,"另一群"), (11,3,"未请求的王")]:
                session.add(Apply(group_id=group, boss=boss, uid=123, time=100, text=text))
            session.add(Tree(group_id=11, boss=2, uid=123, time=100, text="先登记"))
            for lap in (0, 999, 1000):
                session.add(Subscribe(group_id=11, boss=1, uid=123, lap=lap, text="预约"))
            await session.commit()
        event.listen(engine.sync_engine, "before_cursor_execute", count)
        queues = await sql._read_report_queues(11, [1,2,1], subscribers=True)
        assert len(selects) == 3
        assert queues == {1: {"apply": [(123,100,"先登记"), (123,100,"另一留言")], "tree": [],
                              "subscribe": [(123,0,"预约"), (123,999,"预约")]},
                          2: {"apply": [(123,100,"先登记")], "tree": [(123,100,"先登记")], "subscribe": []}}
        selects.clear()
        assert await sql._read_report_queues(11, [5]) == {5: {"apply": [], "tree": [], "subscribe": []}}
        assert len(selects) == 2
        selects.clear()
        assert await sql._read_report_queues(11, []) == {}
        assert selects == []
    finally:
        await engine.dispose()


async def test_report_query_isolates_group_and_game_day_boundaries(app, monkeypatch):
    from src.plugins.priconne.clanbattle import sql
    from src.plugins.priconne.orm.models import Record

    start = int(datetime(2026, 10, 10, 5, tzinfo=timezone(timedelta(hours=8))).timestamp())
    end = start + 86400
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessions = async_sessionmaker(engine)
    monkeypatch.setattr(sql, "get_session", sessions)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(lambda conn: Record.__table__.create(conn))
        async with sessions() as session:
            for log_id, (group, moment) in enumerate(((11, start - 1), (11, start),
                                                    (11, end - 1), (11, end), (22, start)), 1):
                fields = {column.name: 0 for column in Record.__table__.columns if column.name != "id"}
                fields.update(group_id=group, time=moment, pcrid=123, name="成员", boss="1", lap=30,
                              battle_log_id=log_id, damage=log_id * 1000000)
                session.add(Record(**fields))
            await session.commit()
        rows = await sql.RecordDao(11).get_report_records(start, end)
        assert [r["battle_log_id"] for r in rows] == [2, 3]
        assert rows[0]["name"] == "成员" and rows[0]["pcrid"] == 123
        assert [r["damage"] for r in rows] == [2000000, 3000000]
        assert sql.pcr_date(start - 1).day == 9
        assert int(sql.pcr_date(start).timestamp()) == start
        assert await sql.RecordDao(33).get_report_records(start, end) == []
    finally:
        await engine.dispose()


async def test_period_queries_and_correction_exclude_other_events_but_keep_habit_history(app, monkeypatch):
    from src.plugins.priconne.clanbattle import sql
    from src.plugins.priconne.clanbattle.period import BattlePeriod
    from src.plugins.priconne.orm.models import Record

    event = BattlePeriod(42, 1790197200, 1790611200)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessions = async_sessionmaker(engine)
    monkeypatch.setattr(sql, "get_session", sessions)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(lambda conn: Record.__table__.create(conn))
        async with sessions() as session:
            for group, moment, damage in ((11, event.start - 86400 * 30, 900),
                                          (11, event.start + 86400 * 2, 100),
                                          (11, event.end - 1, 200), (11, event.end, 800),
                                          (22, event.start + 86400 * 2, 700)):
                fields = {c.name: 0 for c in Record.__table__.columns if c.name != "id"}
                fields.update(group_id=group, time=moment, pcrid=123, name="成员", boss="1", lap=30,
                              battle_log_id=7, damage=damage, settlement={"manual_flag": 0})
                session.add(Record(**fields))
            await session.commit()
        dao = sql.RecordDao(11, event)
        assert [r["damage"] for r in await dao.get_all_records()] == [100, 200]
        assert (await dao.get_history(7))[2] == 100
        assert await dao.get_full_knife_median_damage(0) == 150
        assert await dao.get_past_damage(30, 1, 123) == 300
        assert await dao.get_latest_time() == event.end - 1
        assert await dao.get_day_rcords(event.start - 1) is None
        assert await dao.get_max_dao(event.start) == 3
        assert await dao.get_max_dao(event.start + 86400 * 2) == 9
        assert await dao.get_max_dao(event.end) == 15
        with pytest.raises(ValueError, match="多条记录"):
            await dao.correct_dao(7, .5)
        preview = await dao.correct_record(2, .5, reason="核对单条记录")
        await dao.correct_record(2, .5, reason="核对单条记录", expected=preview["version"], commit=True)
        await dao.refresh()
        history = await dao.get_report_records(0, event.end + 1)
        assert [(r["damage"], r["flag"]) for r in history] == [(900, 0), (100, 0.5), (200, 0), (800, 0)]
    finally:
        await engine.dispose()


async def test_settlement_query_uses_earlier_tail_context_and_preserves_later_manual_correction(app, monkeypatch):
    from src.plugins.priconne.clanbattle import sql
    from src.plugins.priconne.clanbattle.period import BattlePeriod
    from src.plugins.priconne.orm.models import Record

    period = BattlePeriod(42, 1790197200, 1790611200)
    async def coverage(path):
        return {"record_coverage": dict(event_id=42, start=period.start, through=period.end - 1, complete=True)}
    monkeypatch.setattr(sql, "load_config", coverage)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    monkeypatch.setattr(sql, "get_session", async_sessionmaker(engine))
    try:
        async with engine.begin() as connection:
            await connection.run_sync(lambda conn: Record.__table__.create(conn))
        async with sql.get_session() as session:
            for log, damage, actual, killed in [(1, 500, 100, True), (2, 400, 400, False)]:
                fields = {column.name: 0 for column in Record.__table__.columns if column.name != "id"}
                fields.update(group_id=11, pcrid=123, name="成员", lap=42, boss=str(log),
                              time=period.start + log * 120, damage=damage, battle_log_id=log,
                              remain_time=90, battle_time=90, settlement=dict(
                                  event_id=42, history_damage=actual, killed=killed, history_id=log,
                                  unit_owners=[dict(unit_id=101, viewer_id=123)], owners_complete=True,
                                  report=dict(max_hp=actual, totals={"123": actual}, covered_logs=[["123", log]])
                                  if killed else None))
                session.add(Record(**fields))
            await session.commit()
        dao = sql.RecordDao(11, period)
        later = await dao.get_report_records(period.start + 240, period.start + 241)
        assert len(later) == 1 and later[0]["flag"] == .5 and later[0]["carry_source"] == 1
        stale = await dao.get_settlement_records(period.start, period.end)
        with pytest.raises(ValueError, match="冲突"):
            await dao.correct_dao(2, 0)
        assert await dao.correct_dao(2, .5) == 1
        await dao.save_settlement_facts(stale)
        await dao.bigfun_check([[{"damage_list": [{"datetime": period.start + 240, "damage": 390, "reimburse": 1, "kill": 0}]}]])
        current = await dao.get_report_records(period.start + 240, period.start + 241)
        assert current[0]["flag"] == .5 and current[0]["kind_status"] == "manual"
        assert current[0]["damage"] == 400 and current[0]["effective_damage"] == 390
    finally:
        await engine.dispose()


def test_settlement_migration_preserves_old_rows_and_roundtrips_json(app):
    import importlib.util
    from pathlib import Path
    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    def migration(filename):
        path = Path(__file__).resolve().parents[2] / "src" / "plugins" / "priconne" / "migrations" / filename
        spec = importlib.util.spec_from_file_location(filename, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    initial = migration("e828532300c4_init_priconne_orm.py")
    added = migration("c5e8b2d4a901_add_priconne_settlement.py")
    engine = sa.create_engine("sqlite:///:memory:")
    try:
        with engine.begin() as connection:
            with Operations.context(MigrationContext.configure(connection)):
                initial.upgrade()
                old = sa.Table("priconne_record", sa.MetaData(), autoload_with=connection)
                values = {column.name: 0 for column in old.columns if column.name != "id"}
                values.update(name="旧记录", boss="1", damage=500, flag=1)
                connection.execute(old.insert().values(**values))
                added.upgrade()
                table = sa.Table("priconne_record", sa.MetaData(), autoload_with=connection)
                row = connection.execute(table.select()).mappings().one()
                assert row["damage"] == 500 and row["flag"] == 1 and row["settlement"] is None
                connection.execute(table.update().values(settlement={"manual_flag": .5}))
                assert connection.execute(sa.select(table.c.settlement)).scalar_one() == {"manual_flag": .5}
                added.downgrade()
                assert "settlement" not in {column["name"] for column in sa.inspect(connection).get_columns("priconne_record")}
                assert connection.execute(sa.text("SELECT damage, flag FROM priconne_record")).one() == (500, 1)
    finally:
        engine.dispose()


async def test_damage_declaration_update_and_cancel_preserve_other_groups(app, monkeypatch):
    from src.plugins.priconne.clanbattle import sql
    from src.plugins.priconne.orm.models import Apply

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessions = async_sessionmaker(engine)
    monkeypatch.setattr(sql, "get_session", sessions)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(lambda conn: Apply.__table__.create(conn))
        async with sessions() as session:
            session.add_all([Apply(group_id=11, uid=123, boss=3, time=1, text="旧申报"),
                             Apply(group_id=22, uid=123, boss=3, time=1, text="另一群")])
            await session.commit()
        dao = sql.ApplyDao(11)
        await dao.add_apply(123, 3, "新伤害申报")
        entries = await dao.get_apply(3)
        assert len(entries) == 1 and entries[0][1] > 1 and entries[0][2] == "新伤害申报"
        assert await sql.ApplyDao(22).get_apply(3) == [(123, 1, "另一群")]
        await dao.delete_apply(123)
        assert await dao.get_apply(3) == []
        assert await sql.ApplyDao(22).get_apply(3) == [(123, 1, "另一群")]
    finally:
        await engine.dispose()

async def test_collection_metadata_roundtrips_without_overwriting_manual_correction(app, monkeypatch):
    from src.plugins.priconne.clanbattle import sql
    from src.plugins.priconne.clanbattle.period import BattlePeriod
    from src.plugins.priconne.orm.models import Record

    start = 1790197200
    period = BattlePeriod(42, start, start+5*86400-5*3600)
    engine = create_async_engine('sqlite+aiosqlite:///:memory:')
    monkeypatch.setattr(sql, 'get_session', async_sessionmaker(engine))

    async def config(path):
        return dict(record_coverage=dict(event_id=42, start=start, through=start+100, complete=True))

    monkeypatch.setattr(sql, 'load_config', config)
    owners = dict(event_id=42, unit_owners=[dict(unit_id=101, viewer_id=123), dict(unit_id=102, viewer_id=None)], owners_complete=False)
    old = (123,'成员',start+1,30,'1',500,0,1,90,90,*([0]*30))
    new = (123,'成员',start+2,30,'2',600,0,2,90,90,*([0]*30),owners)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(lambda conn: Record.__table__.create(conn))
        dao = sql.RecordDao(11, period)
        await dao.add_record([old,new])
        rows = await dao.get_settlement_records(start, start+100)
        assert rows[0]['settlement'] is None and rows[1]['settlement'] == owners
        assert all(row['day_complete'] for row in rows)
        stale = [dict(rows[1], settlement=dict(owners, history_id=9))]
        assert await dao.correct_dao(2, .5) == 1
        await dao.save_settlement_facts(stale)
        reread = await dao.get_settlement_records(start, start+100)
        assert reread[1]['settlement']['manual_flag'] == .5
        assert reread[1]['settlement']['unit_owners'] == owners['unit_owners']
        assert [row['damage'] for row in reread] == [500,600]
    finally:
        await engine.dispose()
