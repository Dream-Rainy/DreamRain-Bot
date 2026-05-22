"""priconne 数据库模型 - 基于 nonebot-plugin-orm"""

from sqlalchemy import Integer, BigInteger, Float, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from nonebot_plugin_orm import Model


class WinRecord(Model):
    """猜头像/猜角色游戏胜场记录"""

    gid: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    uid: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=0)


class SL(Model):
    """SL 记录"""

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    uid: Mapped[int] = mapped_column(BigInteger, nullable=False)
    last_sl: Mapped[int] = mapped_column(Integer, nullable=False)


class Subscribe(Model):
    """预约"""

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    uid: Mapped[int] = mapped_column(BigInteger, nullable=False)
    boss: Mapped[int] = mapped_column(Integer, nullable=False)
    lap: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)


class Tree(Model):
    """挂树"""

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    uid: Mapped[int] = mapped_column(BigInteger, nullable=False)
    boss: Mapped[int] = mapped_column(Integer, nullable=False)
    time: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)


class Apply(Model):
    """申请出刀"""

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    uid: Mapped[int] = mapped_column(BigInteger, nullable=False)
    boss: Mapped[int] = mapped_column(Integer, nullable=False)
    time: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)


class Record(Model):
    """出刀记录"""

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    pcrid: Mapped[int] = mapped_column(BigInteger, nullable=False)
    name: Mapped[str] = mapped_column(String(16), nullable=False)
    time: Mapped[int] = mapped_column(Integer, nullable=False)
    lap: Mapped[int] = mapped_column(Integer, nullable=False)
    boss: Mapped[str] = mapped_column(String(16), nullable=False)
    damage: Mapped[int] = mapped_column(Integer, nullable=False)
    flag: Mapped[float] = mapped_column(Float, nullable=False)
    battle_log_id: Mapped[int] = mapped_column(Integer, nullable=False)
    remain_time: Mapped[int] = mapped_column(Integer, nullable=False)
    battle_time: Mapped[int] = mapped_column(Integer, nullable=False)
    unit1: Mapped[int] = mapped_column(Integer, nullable=False)
    unit2: Mapped[int] = mapped_column(Integer, nullable=False)
    unit3: Mapped[int] = mapped_column(Integer, nullable=False)
    unit4: Mapped[int] = mapped_column(Integer, nullable=False)
    unit5: Mapped[int] = mapped_column(Integer, nullable=False)
    unit1_level: Mapped[int] = mapped_column(Integer, nullable=False)
    unit2_level: Mapped[int] = mapped_column(Integer, nullable=False)
    unit3_level: Mapped[int] = mapped_column(Integer, nullable=False)
    unit4_level: Mapped[int] = mapped_column(Integer, nullable=False)
    unit5_level: Mapped[int] = mapped_column(Integer, nullable=False)
    unit1_damage: Mapped[int] = mapped_column(Integer, nullable=False)
    unit2_damage: Mapped[int] = mapped_column(Integer, nullable=False)
    unit3_damage: Mapped[int] = mapped_column(Integer, nullable=False)
    unit4_damage: Mapped[int] = mapped_column(Integer, nullable=False)
    unit5_damage: Mapped[int] = mapped_column(Integer, nullable=False)
    unit1_rarity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit2_rarity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit3_rarity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit4_rarity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit5_rarity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit1_rank: Mapped[int] = mapped_column(Integer, nullable=False)
    unit2_rank: Mapped[int] = mapped_column(Integer, nullable=False)
    unit3_rank: Mapped[int] = mapped_column(Integer, nullable=False)
    unit4_rank: Mapped[int] = mapped_column(Integer, nullable=False)
    unit5_rank: Mapped[int] = mapped_column(Integer, nullable=False)
    unit1_unique_equip: Mapped[int] = mapped_column(Integer, nullable=False)
    unit2_unique_equip: Mapped[int] = mapped_column(Integer, nullable=False)
    unit3_unique_equip: Mapped[int] = mapped_column(Integer, nullable=False)
    unit4_unique_equip: Mapped[int] = mapped_column(Integer, nullable=False)
    unit5_unique_equip: Mapped[int] = mapped_column(Integer, nullable=False)
