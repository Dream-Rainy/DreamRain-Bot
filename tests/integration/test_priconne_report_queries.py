from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


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
        assert await dao.correct_dao(7, 0.5) == 1
        await dao.refresh()
        history = await dao.get_report_records(0, event.end + 1)
        assert [(r["damage"], r["flag"]) for r in history] == [(900, 0), (100, 0.5), (200, 0.5), (800, 0)]
    finally:
        await engine.dispose()


async def test_settlement_query_uses_earlier_tail_context_and_preserves_later_manual_correction(app, monkeypatch):
    from src.plugins.priconne.clanbattle import sql
    from src.plugins.priconne.clanbattle.period import BattlePeriod
    from src.plugins.priconne.orm.models import Record

    period = BattlePeriod(42, 1790197200, 1790611200)
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
                                  event_id=42, history_damage=actual, killed=killed, history_id=log))
                session.add(Record(**fields))
            await session.commit()
        dao = sql.RecordDao(11, period)
        later = await dao.get_report_records(period.start + 240, period.start + 241)
        assert len(later) == 1 and later[0]["flag"] == .5 and later[0]["carry_source"] == 1
        stale = await dao.get_settlement_records(period.start, period.end)
        assert await dao.correct_dao(2, 0) == 1
        await dao.save_settlement_facts(stale)
        await dao.bigfun_check([[{"damage_list": [{"datetime": period.start + 240, "damage": 390, "reimburse": 1, "kill": 0}]}]])
        current = await dao.get_report_records(period.start + 240, period.start + 241)
        assert current[0]["flag"] == 0 and current[0]["kind_status"] == "manual"
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
        path = Path(__file__).resolve().parents[2] / "migrations" / "versions" / filename
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
