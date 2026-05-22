"""猜头像、猜角色小游戏"""

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from ..orm import get_session
from ..orm.models import WinRecord


class Dao:
    """异步 DAO，基于 nonebot-plugin-orm"""

    async def get_win_count(self, gid: int, uid: int) -> int:
        async with get_session() as sess:
            r = await sess.execute(
                select(WinRecord.count).where(
                    WinRecord.gid == gid, WinRecord.uid == uid
                )
            )
            row = r.scalar_one_or_none()
            return row if row is not None else 0

    async def record_winning(self, gid: int, uid: int) -> int:
        n = await self.get_win_count(gid, uid)
        n += 1
        async with get_session() as sess:
            stmt = insert(WinRecord).values(gid=gid, uid=uid, count=n)
            stmt = stmt.on_conflict_do_update(
                index_elements=["gid", "uid"],
                set_={"count": n},
            )
            await sess.execute(stmt)
            await sess.commit()
        return n

    async def get_ranking(self, gid: int) -> list[tuple[int, int]]:
        async with get_session() as sess:
            r = await sess.execute(
                select(WinRecord.uid, WinRecord.count)
                .where(WinRecord.gid == gid)
                .order_by(WinRecord.count.desc())
                .limit(10)
            )
            return list(r.all())


class GameMaster:
    def __init__(self):
        self.playing: dict[int, "Game"] = {}
        self._dao = Dao()

    def is_playing(self, gid: int) -> bool:
        return gid in self.playing

    def start_game(self, gid: int) -> "Game":
        return Game(gid, self)

    def get_game(self, gid: int) -> "Game | None":
        return self.playing.get(gid)

    @property
    def db(self) -> Dao:
        return self._dao


class Game:
    def __init__(self, gid: int, game_master: GameMaster):
        self.gid = gid
        self.gm = game_master
        self.answer: int | tuple = 0
        self.winner: int = 0

    def __enter__(self):
        self.gm.playing[self.gid] = self
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.gm.playing.pop(self.gid, None)

    async def record(self) -> int:
        return await self.gm.db.record_winning(self.gid, self.winner)


from . import desc_guess
from . import avatar_guess
