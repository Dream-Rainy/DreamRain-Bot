import os
import asyncio
import traceback
from time import time as timestamp
from nonebot import logger
from .base import CancleError, find_item, format_bignum, format_precent, clan_path
from .sql import RecordDao, SubscribeDao, TreeDao, ApplyDao, clear_period_registrations
from .period import get_period
from ..util.tools import load_config, write_config, lap2stage, stage_dict
from ..pcrclient import ApiException


class ClanBattle:
    def __init__(self, group_id) -> None:
        self.rank = 0  # 会战排名
        self.user_name = ""  # 游戏内昵称
        self.period = 0  # 阶段
        self.lap_num = 0  # 周目（会战周目，boss可能多一周目）
        self.loop_num = 0  # 循环编号
        self.error_count = 0  # 失败计数
        self.loop_check = False  # 循环检查
        self.group_id = group_id
        self.event = None
        self.record_sync_lock = asyncio.Lock()
        self.notice_dao = []
        self.notice_tree = []
        self.notice_fighter = []
        self.notice_subscribe = []
        self.notice_coop = []
        self.boss = [Boss(), Boss(), Boss(), Boss(), Boss()]

    def init_database(self):
        self.record = RecordDao(self.group_id, self.event)
        self.subscribe = SubscribeDao(self.group_id)
        self.tree = TreeDao(self.group_id)
        self.apply = ApplyDao(self.group_id)

    async def init(self, client, qq_id):
        try:
            self.loop_num += 1
            self.client = client  # api client
            self.qq_id = qq_id
            await self.refresh_user_name()
            home_index = await self.client.callapi('/home/index', {'message_id': 1, 'tips_id_list': [], 'is_first': 1, 'gold_history': 0})
            self.clan_id = home_index['user_clan']['clan_id']
            clan_battle_top = await self.get_clanbattle_top()
            self.init_database()
            await self.bind_period(clan_battle_top["clan_battle_id"])
            self.lap_num = clan_battle_top["lap_num"]
            self.period = stage_dict[lap2stage(self.lap_num)]
            self.refresh_latest_time(clan_battle_top)
            # 记录群成员
            await self.save_member(os.path.join(clan_path, f'{self.group_id}', "clanbattle.json"))
        except Exception as e:
            print(traceback.format_exc())
            raise Exception(f"数据库初始化失败 + {str(e)}")

    async def bind_period(self, event_id):
        if self.event is not None and self.event.id == event_id:
            return
        event = await get_period(event_id=event_id)
        path = os.path.join(clan_path, str(self.group_id), "clanbattle.json")
        config = await load_config(path) or {}
        if config.get("clan_battle_id") != event.id:
            await clear_period_registrations(self.group_id)
            self.boss = [Boss(), Boss(), Boss(), Boss(), Boss()]
            for notices in (self.notice_dao, self.notice_tree, self.notice_fighter,
                            self.notice_subscribe, self.notice_coop):
                notices.clear()
            self.latest_time = event.start - 1
            config.update(clan_battle_id=event.id, battle_start=event.start, battle_end=event.end - 1)
            await write_config(path, config)
        self.event = event
        self.clan_battle_id = event.id
        self.record = RecordDao(self.group_id, event)

    async def rebind_client(self, client):
        self.client = client
        await self.refresh_user_name()

    async def refresh_user_name(self):
        """从 /load/index 读取游戏内昵称，失败时保留旧值。"""
        try:
            load_index = await self.client.callapi('/load/index', {'carrier': 'OPPO'})
            if isinstance(load_index, dict) and load_index.get("user_info"):
                name = load_index["user_info"].get("user_name")
                if name:
                    self.user_name = name
        except Exception:
            pass
        return self.user_name

    async def probe_session(self):
        """探测当前 client 会话状态，用于区分顶号与普通错误。

        返回 (reachable, status, message):
          reachable=True  -> 会话正常，可继续监控；
          reachable=False -> 会话异常，status/message 为服务端返回的原始错误码与信息，
                             供上层判断是否为「已在其他设备登录」而决定是否重连。
        """
        try:
            load_index = await self.client.callapi('/load/index', {'carrier': 'OPPO'})
        except ApiException as e:
            logger.warning(f"priconne probe_session ApiException: code={getattr(e, 'code', None)}, msg={e}")
            return False, getattr(e, "code", None), str(e)
        except Exception as e:
            logger.warning(f"priconne probe_session unexpected error: {e!r}")
            return False, None, str(e)
        if isinstance(load_index, dict) and "server_error" in load_index:
            err = load_index.get("server_error") or {}
            status = err.get("status")
            message = err.get("message", "")
            title = err.get("title", "")
            logger.warning(
                f"priconne probe_session server_error: status={status}, "
                f"title={title!r}, message={message!r}, raw={err!r}"
            )
            return False, status, message
        return True, None, ""

    async def get_coin(self):
        load_index = await self.client.callapi('/load/index', {'carrier': 'OPPO'})
        return find_item(load_index["item_list"], 90006)

    async def get_clanbattle_top(self):
        return await self.client.callapi('/clan_battle/top', {"clan_id": self.clan_id, "is_first": 0, "current_clan_battle_coin": await self.get_coin()})

    async def save_member(self, config_file):
        member_dict = {}
        members = await self.client.callapi('/clan/info', {'clan_id': self.clan_id, 'get_user_equip': 0})
        for member in members["clan"]["members"]:
            member_dict[member["name"]] = member["viewer_id"]
        config = dict(await load_config(config_file))
        config["member"] = member_dict
        config["member_by_id"] = {
            str(member["viewer_id"]): member["name"]
            for member in members["clan"]["members"]
        }
        config["member_updated_at"] = int(timestamp())
        await write_config(config_file, config)

    async def refresh_fighter_num(self, lap_num, order):
        boss: Boss = self.boss[order-1]
        try:
            if boss.check_available(lap_num, self.period):  # 不能超过两个周目，不能跨阶段
                reload_detail_info = await self.client.callapi('/clan_battle/reload_detail_info',
                                                               {"clan_id": self.clan_id, "clan_battle_id": self.clan_battle_id, "lap_num": lap_num, "order_num": order})
                reload_detail_info["fighter_num"]
                boss.fighter_updated_at = timestamp()
                boss.fighter_lap = lap_num
                if reload_detail_info["fighter_num"] != boss.fighter_num:
                    boss.fighter_num = reload_detail_info["fighter_num"]
                    return reload_detail_info["fighter_num"]
        except Exception:
            return 0
        return 0  # 0不播报，没改变不报，改变了是0也不报

    async def get_battle_log(self, page):
        return await self.client.callapi('/clan_battle/battle_log_list',  {
            "clan_battle_id": self.clan_battle_id,
            "order_num": 0,
            "phases": [1, 2, 3, 4],
            "report_types": [1, 2, 3],
            "hide_same_units": 0,
            "favorite_ids": [],
            "sort_type": 4,
            "page": page,
        }
        )

    async def add_record(self, damage_history, loop_num):
        async with self.record_sync_lock:
            return await self._add_record(damage_history, loop_num)

    async def sync_final_records(self, period):
        if self.event is None or self.event.id != period.id:
            return False
        loop_num = self.loop_num
        try:
            top = await self.get_clanbattle_top()
        except Exception:
            top = {}
        if top.get("clan_battle_id") not in (None, 0, period.id) or loop_num != self.loop_num:
            return False
        return await self.add_record(top.get("damage_history", []), loop_num)

    async def _add_record(self, damage_history, loop_num):
        log_list = []
        dao_list = []
        try:
            if loop_num != self.loop_num:
                raise CancleError
            log_temp = await self.get_battle_log(1)  # 获取最大页数
            if not log_temp["battle_list"]:
                if loop_num != self.loop_num:
                    raise CancleError
                return True

            max_page = log_temp["max_page"]
            latest_time = await self.record.get_latest_time()
            seen = set()
            if latest_time and self.event is not None:
                recent = await self.record.get_report_records(latest_time, self.event.end)
                seen = {(str(row["pcrid"]), row["battle_log_id"]) for row in recent}
            for page in range(max_page, 0, -1):
                log = await self.get_battle_log(page)
                if log["battle_list"][-1]["battle_end_time"] >= latest_time:
                    log_list += log["battle_list"][::-1]
                else:
                    break

            for record in log_list[::-1]:
                if loop_num != self.loop_num:
                    raise CancleError

                if self.event is not None and not self.event.start <= record["battle_end_time"] < self.event.end:
                    continue

                key = (str(record["target_viewer_id"]), record["battle_log_id"])
                if ((time := record["battle_end_time"]) >= int(latest_time)
                        and record["battle_type"] == 1 and key not in seen):
                    pcrid = record["target_viewer_id"]
                    name = record["user_name"]
                    boss = record["order_num"]
                    lap = record["lap_num"]
                    damage = record['total_damage']
                    battle_log_id = record['battle_log_id']
                    units_list = [0 for i in range(30)]
                    for i, unit in enumerate(record["units"]):
                        units_list[i] = unit["unit_id"]
                        units_list[i + 5] = unit["unit_level"]
                        units_list[i + 10] = unit["damage"]
                        units_list[i + 15] = unit["unit_rarity"]
                        units_list[i + 20] = unit["promotion_level"]
                        units_list[i + 25] = unit["unique_equip_slot"][0]["enhancement_level"] if unit["unique_equip_slot"] else 0
                    # 故意不重试，这循环极端情况下运行10分钟也正常，不如报错趁早退出，下次再来
                    time_line = await self.client.callapi('/clan_battle/timeline_report', {"target_viewer_id": pcrid, "clan_battle_id": self.clan_battle_id, "battle_log_id": battle_log_id})
                    remain_time, battle_time = time_line["start_remain_time"], time_line["battle_time"]
                    flag = 0 if remain_time == 90 else 0.5
                    if battle_time < 90 and flag == 0:
                        flag = 1
                        if damage_history and damage_history[-1]["create_time"] <= time <= damage_history[0]["create_time"]:
                            for history in damage_history:
                                if history["create_time"] == time and not history["kill"]:
                                    flag = 0
                                    break
                    # FIXME:开销有点大
                    """
                    # 伤害修正开始
                    if flag == 1:
                        damage_report = await self.client.callapi('/clan_battle/damage_report', {'clan_id': int(self.clan_id), 'clan_battle_id': int(self.clan_battle_id), 'lap_num': int(lap), 'order_num': int(boss)})
                        for it in damage_report['damage_report']:
                            if pcrid in it:
                                damage_fix = it['damage']
                                damage = damage_fix - self.record.get_past_damage(lap, boss, pcrid)
                                break
                    # 伤害修正结束
                    """

                    dao_list.append((pcrid, name, time, lap, boss, damage, flag,
                                    battle_log_id, remain_time, battle_time, *units_list))
                    seen.add(key)
            if loop_num != self.loop_num:
                raise CancleError
            await self.record.add_record(dao_list)
        except CancleError:
            raise
        except Exception as e:
            # 批次不完整时不推进最新记录时间，下轮可重取失败记录。
            logger.opt(exception=e).warning(f"公会战战绩同步失败，group={self.group_id}")
            return False
        return True

    def refresh_latest_time(self, clan_battle_top):
        try:
            self.latest_time = clan_battle_top["damage_history"][0]["create_time"]
        except:
            self.latest_time = 0

    def general_boss(self):
        return "当前进度：" + f"{lap2stage(self.lap_num)}面{self.period}阶段\n" + "\n".join([boss.boss_info(self.lap_num, self.period) for boss in self.boss])


class Boss:
    def __init__(self) -> None:
        self.stage = 0
        self.order = 0
        self.max_hp = 0
        self.lap_num = 0
        self.stage_num = 0
        self.current_hp = 0
        self.fighter_num = 0
        self.fighter_updated_at = 0
        self.fighter_lap = 0
        self.coop_notified = False  # 本 boss 已提醒过合刀
        self.last_kill_name = ""  # 最近一次击杀本 boss 的玩家名
        self.last_kill_time = 0   # 最近一次击杀时间戳

    def refresh(self, current_hp, lap_num, order, max_hp):
        self.current_hp = current_hp
        self.lap_num = lap_num
        self.order = order
        self.max_hp = max_hp
        self.stage = lap2stage(lap_num)
        self.stage_num = stage_dict[self.stage]

    def boss_info(self, lap_num, period):
        msg = f'{self.lap_num}周目{self.order}王: '
        if self.check_available(lap_num, period) and self.current_hp:
            msg += f'HP: {format_bignum(self.current_hp)}/{format_bignum(self.max_hp)} {format_precent(self.current_hp/self.max_hp)}'
            if self.fighter_num:
                msg += f" 当前有{self.fighter_num}人挑战"
        else:
            msg += "无法挑战"
        return msg

    def check_available(self, lap_num, period):
        return self.lap_num - lap_num < 2 and self.stage_num == period
