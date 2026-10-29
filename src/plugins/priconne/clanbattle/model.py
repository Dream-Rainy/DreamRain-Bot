import os
import asyncio
import traceback
from time import time as timestamp
from nonebot import logger
from .base import CancleError, find_item, format_bignum, format_precent, clan_path
from .sql import RecordDao, SubscribeDao, TreeDao, ApplyDao, clear_period_registrations
from .period import get_period
from .settlement import analyse_records, facts
from ..util.tools import load_config, write_config, lap2stage, stage_dict
from ..pcrclient import ApiException, _is_retryable_error


class ClanBattle:
    def __init__(self, group_id) -> None:
        self.rank = 0  # 会战排名
        self.rank_at = 0
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
        self.settlements = {}
        self.collection_facts = {}
        self.record_coverage = {}
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
            home_index = await self.client.callapi('/home/index', {'message_id': 1, 'tips_id_list': [], 'is_first': 1, 'gold_history': 0}, noerr=False)
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
            config.pop("record_coverage", None)
            config.update(clan_battle_id=event.id, battle_start=event.start, battle_end=event.end - 1)
            await write_config(path, config)
        self.rank, self.rank_at = 0, 0
        self.collection_facts = {}
        self.record_coverage = config.get("record_coverage", {})
        self.event = event
        self.clan_battle_id = event.id
        self.record = RecordDao(self.group_id, event)

    def update_rank(self, rank, now):
        if (self.event is not None and type(now) in (int, float) and self.event.active(now)
                and type(rank) is int and rank > 0):
            self.rank, self.rank_at = rank, int(now)
            return True
        return False

    async def rebind_client(self, client):
        self.client = client
        await self.refresh_user_name()

    async def refresh_user_name(self):
        """从 /load/index 读取游戏内昵称，失败时保留旧值。"""
        try:
            load_index = await self.client.callapi('/load/index', {'carrier': 'OPPO'}, noerr=False)
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
            load_index = await self.client.callapi('/load/index', {'carrier': 'OPPO'}, noerr=False)
        except ApiException as e:
            logger.warning(f"priconne probe_session ApiException: code={getattr(e, 'code', None)}, msg={e}")
            return False, None if e.code == 501 else e.code, str(e)
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
        load_index = await self.client.callapi('/load/index', {'carrier': 'OPPO'}, noerr=False)
        return find_item(load_index["item_list"], 90006)

    async def get_clanbattle_top(self):
        return await self.client.callapi('/clan_battle/top', {"clan_id": self.clan_id, "is_first": 0, "current_clan_battle_coin": await self.get_coin()}, noerr=False)

    async def save_member(self, config_file):
        member_dict = {}
        members = await self.client.callapi('/clan/info', {'clan_id': self.clan_id, 'get_user_equip': 0}, noerr=False)
        detail = members["clan"].get("detail") or {}
        self.clan_leader_id = detail.get("leader_viewer_id")
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
                                                               {"clan_id": self.clan_id, "clan_battle_id": self.clan_battle_id, "lap_num": lap_num, "order_num": order}, noerr=False)
                reload_detail_info["fighter_num"]
                boss.fighter_updated_at = timestamp()
                boss.fighter_lap = lap_num
                if reload_detail_info["fighter_num"] != boss.fighter_num:
                    boss.fighter_num = reload_detail_info["fighter_num"]
                    return reload_detail_info["fighter_num"]
        except Exception as error:
            if isinstance(error, ApiException) or _is_retryable_error(error):
                raise
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
        }, noerr=False)

    async def add_record(self, damage_history, loop_num, boss_info=None):
        async with self.record_sync_lock:
            success = await self._add_record(damage_history, loop_num)
            if success and self.event is not None:
                try:
                    await self._enrich_records(damage_history, boss_info or [], loop_num)
                except CancleError:
                    raise
                except Exception as error:
                    if isinstance(error, ApiException) or _is_retryable_error(error):
                        raise
                    logger.opt(exception=error).warning(f"结算依据补采失败，group={self.group_id}")
            return success

    async def _enrich_records(self, history, boss_info, loop_num):
        records = await self.record.get_settlement_records(self.event.start, self.event.end)
        groups, changed = {}, []
        matches = {}
        counts = {}
        for row in records:
            key = (str(row["pcrid"]), row["lap"], str(row["boss"]), row["time"])
            counts[key] = counts.get(key, 0) + 1
        for item in history:
            key = (str(item.get("viewer_id")), item.get("lap_num"), str(item.get("order_num")), item.get("create_time"))
            matches.setdefault(key, []).append(item)
        for row in records:
            previous = facts(row)
            meta = dict(previous, event_id=self.event.id)
            captured = self.collection_facts.get((str(row["pcrid"]), row["battle_log_id"]))
            if captured and (captured.get("owners_complete") or not previous.get("owners_complete")):
                meta.update(captured)
            key = (str(row["pcrid"]), row["lap"], str(row["boss"]), row["time"])
            found = matches.get(key, [])
            if len(found) == 1 and counts[key] == 1:
                item = found[0]
                if type(item.get("damage")) is int and 0 <= item["damage"] <= row["damage"] and item.get("kill") in (0, 1):
                    meta.update(history_damage=item["damage"], killed=bool(item["kill"]))
                    if type(item.get("history_id")) is int and item["history_id"] > 0:
                        meta["history_id"] = item["history_id"]
            elif counts[key] > 1:
                for field in ("history_damage", "killed", "history_id"):
                    meta.pop(field, None)
            for boss in boss_info:
                if boss.get("lap_num") == row["lap"] and str(boss.get("order_num")) == str(row["boss"]):
                    meta["max_hp"] = boss.get("max_hp")
            row["settlement"] = meta
            if meta != previous:
                changed.append(row)
            groups.setdefault((row["lap"], row["boss"]), []).append(row)
        for (lap, boss), rows in groups.items():
            if all(type(facts(row).get("history_damage")) is int and facts(row).get("killed") is False for row in rows):
                continue
            logs = sorted([[str(row["pcrid"]), row["battle_log_id"]] for row in rows])
            if any(isinstance(facts(row).get("report"), dict) and facts(row)["report"].get("covered_logs") == logs for row in rows):
                continue
            if not getattr(self, "clan_id", None):
                continue
            if loop_num != self.loop_num:
                raise CancleError
            try:
                report = await self.client.callapi('/clan_battle/damage_report', {
                    "clan_id": int(self.clan_id), "clan_battle_id": self.event.id,
                    "lap_num": lap, "order_num": int(boss),
                }, noerr=False)
                maximum, items = report.get("max_hp"), report.get("damage_report")
                if type(maximum) is not int or maximum <= 0 or not isinstance(items, list):
                    continue
                totals = {}
                for item in items:
                    uid, amount = item.get("viewer_id"), item.get("damage")
                    if not uid or type(amount) is not int or amount < 0 or str(uid) in totals:
                        raise ValueError("成员累计扣血无效")
                    totals[str(uid)] = amount
                rows[0]["settlement"] = dict(facts(rows[0]), report=dict(
                    max_hp=maximum, totals=totals, covered_logs=logs, observed_at=int(timestamp())))
                if rows[0] not in changed:
                    changed.append(rows[0])
            except Exception as error:
                if isinstance(error, ApiException) or _is_retryable_error(error):
                    raise
                logger.opt(exception=error).warning(f"王伤害核验失败，group={self.group_id}, lap={lap}, boss={boss}")
        if loop_num != self.loop_num:
            raise CancleError
        if changed:
            await self.record.save_settlement_facts(changed)
        analysed = await asyncio.to_thread(analyse_records, records)
        self.settlements = {(str(row["pcrid"]), row["lap"], str(row["boss"]), row["time"]): row for row in analysed}

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
        return await self.add_record(top.get("damage_history", []), loop_num, top.get("boss_info", []))

    async def _add_record(self, damage_history, loop_num):
        dao_list, captured, known = [], {}, []
        observed_at = int(timestamp())
        try:
            if loop_num != self.loop_num:
                raise CancleError
            coverage = self.record_coverage if isinstance(self.record_coverage, dict) else {}
            full_scan = not (self.event and coverage.get("event_id") == self.event.id and coverage.get("complete") is True)
            latest_time = await self.record.get_latest_time()
            if self.event is not None and latest_time:
                known = await self.record.get_report_records(self.event.start if full_scan else latest_time, self.event.end)
            seen = {(str(row["pcrid"]), row["battle_log_id"]) for row in known}
            existing_keys = set(seen)
            first = await self.get_battle_log(1)
            max_page = max(1, int(first["max_page"])) if first["battle_list"] else 1
            log_list, visited, overlap, stable = [], set(), False, True
            for page in range(max_page, 0, -1):
                log = first if page == 1 else await self.get_battle_log(page)
                if loop_num != self.loop_num:
                    raise CancleError
                entries = log["battle_list"]
                stable = stable and int(log.get("max_page", max_page) or 1) == max_page
                visited.add(page)
                overlap = overlap or any((str(item["target_viewer_id"]), item["battle_log_id"]) in seen for item in entries)
                log_list.extend(entries)
                if not full_scan and entries and max(item["battle_end_time"] for item in entries) < latest_time:
                    break
            visible = [(str(r["target_viewer_id"]), r["battle_log_id"]) for r in log_list if r["battle_type"] == 1]
            stable = stable and len(visible) == len(set(visible))
            complete = stable and ((full_scan and len(visited) == max_page) or (not full_scan and overlap))
            keys = {(str(r["pcrid"]), r["lap"], str(r["boss"]), r["time"]) for r in known if all(k in r for k in ("lap", "boss", "time"))}
            for record in sorted(log_list, key=lambda item: (item["battle_end_time"], item["battle_log_id"])):
                if loop_num != self.loop_num:
                    raise CancleError
                time = record["battle_end_time"]
                if record["battle_type"] != 1 or (not full_scan and time < latest_time) or (self.event is not None and not self.event.start <= time < self.event.end):
                    continue
                pcrid, battle_log_id = record["target_viewer_id"], record["battle_log_id"]
                key = str(pcrid), battle_log_id
                units = record["units"]
                owners = [{"unit_id": u.get("unit_id"), "viewer_id": u.get("viewer_id") if type(u.get("viewer_id")) is int and u["viewer_id"] > 0 else None} for u in units]
                owners_complete = bool(owners) and len(owners) <= 5 and all(type(u["unit_id"]) is int and u["unit_id"] > 0 and u["viewer_id"] is not None for u in owners)
                owners_complete = owners_complete and len({u["unit_id"] for u in owners}) == len(owners)
                meta = dict(unit_owners=owners, owners_complete=owners_complete)
                if self.event is not None:
                    meta["event_id"] = self.event.id
                captured[key] = meta
                keys.add((str(pcrid), record["lap_num"], str(record["order_num"]), time))
                if key in seen:
                    continue
                units_list = [0] * 30
                for i, unit in enumerate(units):
                    units_list[i] = unit["unit_id"]
                    units_list[i + 5] = unit["unit_level"]
                    units_list[i + 10] = unit["damage"]
                    units_list[i + 15] = unit["unit_rarity"]
                    units_list[i + 20] = unit["promotion_level"]
                    units_list[i + 25] = unit["unique_equip_slot"][0]["enhancement_level"] if unit["unique_equip_slot"] else 0
                timeline = await self.client.callapi('/clan_battle/timeline_report', {"target_viewer_id": pcrid, "clan_battle_id": self.clan_battle_id, "battle_log_id": battle_log_id}, noerr=False)
                remain_time, battle_time = timeline["start_remain_time"], timeline["battle_time"]
                flag = 0 if remain_time == 90 else .5
                dao_list.append((pcrid, record["user_name"], time, record["lap_num"], record["order_num"], record["total_damage"], flag,
                                 battle_log_id, remain_time, battle_time, *units_list, meta))
                seen.add(key)
            if full_scan:
                complete = complete and existing_keys <= set(captured)
            for item in damage_history:
                if (self.event is None or self.event.start <= item["create_time"] < self.event.end) and (full_scan or item["create_time"] >= latest_time):
                    complete = complete and (str(item.get("viewer_id")), item["lap_num"], str(item["order_num"]), item["create_time"]) in keys
            if loop_num != self.loop_num:
                raise CancleError
            await self.record.add_record(dao_list)
            if loop_num != self.loop_num:
                raise CancleError
            self.collection_facts = captured
            if self.event is not None:
                config_path = os.path.join(clan_path, str(self.group_id), "clanbattle.json")
                config = await load_config(config_path) or {}
                if loop_num != self.loop_num:
                    raise CancleError
                new_coverage = dict(event_id=self.event.id, start=self.event.start,
                                    through=min(observed_at, self.event.end - 1) if complete else coverage.get("through", 0), complete=complete)
                config.update(clan_battle_id=self.event.id, record_coverage=new_coverage)
                await write_config(config_path, config)
                self.record_coverage = new_coverage
        except CancleError:
            raise
        except Exception as error:
            logger.opt(exception=error).warning(f"公会战战绩同步失败，group={self.group_id}")
            if isinstance(error, ApiException) or _is_retryable_error(error):
                raise
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
