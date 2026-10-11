"""国服会战期次；日程表的 end_time 包含结算展示期，不能作为出刀截止时间。"""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import sqlite3
import time

from nonebot_plugin_localstore import get_data_dir

GAME_TZ = timezone(timedelta(hours=8))
SCHEDULE_DB = get_data_dir("kanna_note") / "resource" / "data" / "pcr_cn.db"


@dataclass(frozen=True)
class BattlePeriod:
    id: int
    start: int
    end: int  # 排他边界：第五天结束后的 00:00:00。

    def active(self, now):
        return self.start <= now < self.end

    def days(self, now):
        first = datetime.fromtimestamp(self.start, GAME_TZ).date()
        day = (datetime.fromtimestamp(now, GAME_TZ) - timedelta(hours=5)).date()
        return max(0, min(5, (day - first).days + 1))

    def quota(self, now):
        return self.days(now) * 3

    def label(self, now):
        start = datetime.fromtimestamp(self.start, GAME_TZ)
        end = datetime.fromtimestamp(self.end - 1, GAME_TZ)
        status = "未开始" if now < self.start else (
            "已结束" if now >= self.end else f"第{self.days(now)}/5天"
        )
        return (f"第{self.id}期｜{start:%Y-%m-%d %H:%M:%S} 至 {end:%m-%d %H:%M:%S}（UTC+8）"
                f"\n{status}｜每日3刀，整期15刀｜累计应出{self.quota(now)}刀/人")


def _read_period(now, event_id):
    try:
        with sqlite3.connect(SCHEDULE_DB.resolve().as_uri() + "?mode=ro", uri=True) as db:
            if event_id is not None:
                rows = db.execute(
                    "SELECT clan_battle_id, start_time FROM clan_battle_schedule WHERE clan_battle_id=?",
                    (event_id,),
                ).fetchall()
            else:
                rows = db.execute("SELECT clan_battle_id, start_time FROM clan_battle_schedule").fetchall()
        periods = []
        for identifier, value in rows:
            start = datetime.strptime(value, "%Y/%m/%d %H:%M:%S").replace(tzinfo=GAME_TZ)
            end = start.replace(hour=0, minute=0, second=0) + timedelta(days=5)
            period = BattlePeriod(int(identifier), int(start.timestamp()), int(end.timestamp()))
            if period.id > 0 and (event_id is not None or period.start <= now):
                periods.append(period)
        if periods:
            return max(periods, key=lambda period: period.start)
    except (sqlite3.Error, ValueError, TypeError, OSError):
        pass
    raise ValueError("会战期次或开战日期缺失，请执行【更新wiki数据库】后重试；未使用其他期战绩。")


async def get_period(now=None, event_id=None):
    return await asyncio.to_thread(_read_period, time.time() if now is None else now, event_id)
