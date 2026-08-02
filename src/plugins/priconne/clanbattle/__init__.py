import re
import os
import math
import traceback
import time
import asyncio

from zoneinfo import ZoneInfo

from nonebot import get_bot, get_driver, logger

from ..captcha import CaptchaContext
from ..compat import Service, priv, on_startup
from ..compat.typing import NoticeSession
from ..credentials import build_stored_account, should_update_stored_account
from ..login import query
from ..util.tools import load_config, write_config, safe_send, check_client, DATA_PATH, stage_dict
from .base import *
from .model import ClanBattle
from .kpi import kpi_report
from .sql import SubscribeDao, RecordDao, SLDao, TreeDao, ApplyDao, clear_group_data
from .pcr_calculator import calculator

from ..pcrclient import init_device_id, ApiException

help_text = '''
* “+” 表示空格
【出刀监控】机器人登录账号，监视出刀情况并记录
【催刀】栞栞谁没出满三刀
【当前战报】本期会战出刀情况
【我的战报 + 游戏名称】 栞栞个人出刀情况
【今日战报 + 游戏名称】 栞栞今日个人出刀情况
【昨日战报 + 游戏名称】 栞栞昨日个人出刀情况
【出刀详情 + 出刀编号】 栞栞你这刀怎么出的（出刀编号可以通过查看个人战报获得）
【今日出刀】今日出刀情况
【昨日出刀】昨日出刀情况
【启用肃正协议】数据出现异常使用即可清空所有数据（危险！！！）
【修正出刀 + 出刀编号 + （完整刀|尾刀|补偿）】修正错误的刀数记录
【状态】查看当前进度
【boss状态】看看boss里面有几个人
【预约表】栞栞谁预约了
【预约 + 数字 + （周目）+ （留言） 】预约boss, 周目和留言可不写，默认当前周目
【取消预约 + （数字）】取消预约
【清空预约 + （数字）】（仅）管理，清空预约
【查树】栞栞树上有几个人
【下树】寄，掉刀了
【挂树 + 数字】失误了, 寄
【sl】记录sl
【sl?】栞栞今天有没有用过sl
【申请出刀 + 数字 + （留言） 】 申请打boss，boss死亡自动清空
【取消申请】 模拟10次挂10次，老子不打了
'''.strip()

clanbattle_info = {}
run_group = {}
semaphore = asyncio.Semaphore(40)

sv = Service(
    name="真-自动报刀remix",  # 功能名
    visible=True,  # 可见性
    enable_on_default=True,  # 默认启用
    help_=help_text,  # 帮助说明
)

@sv.on_fullmatch('自动报刀帮助')
async def query_help(bot, ev):
    await bot.send(ev, help_text)


@sv.on_fullmatch('出刀监控')
async def add_monitor(bot, ev):
    qq_id = ev.user_id

    for m in ev.message:
        if m.type == 'at' and m.data.get('qq') != 'all':
            if not priv.check_priv(ev, priv.ADMIN):
                await bot.send(ev, '权限不足')
                return
            qq_id = int(m.data['qq'])
            break

    group_id = ev.group_id
    account_file = os.path.join(DATA_PATH, 'account', f'{qq_id}.json')
    acccountinfo = await load_config(account_file)

    if not acccountinfo:
        await bot.send(ev, "你没有绑定账号")
        return

    account_info = acccountinfo[0]
    account = account_info.get("account") or account_info.get("viewer_id")
    account_mask = f"{account[:3]}******{account[-3:]}" if account else "未知账号"
    await bot.send(ev, f"正在登录账号，请耐心等待，当前监控账号为{account_info.get('user_name') or account_mask}")
    
    try:
        captcha_context = CaptchaContext(bot=bot, user_id=qq_id, group_id=group_id)
        client = await query(acccountinfo, captcha_context=captcha_context)
        if not await check_client(client):
            raise Exception("登录异常，请重试")
        if should_update_stored_account(account_info, client.uid, client.access_key):
            try:
                acccountinfo[0] = build_stored_account(account_info, client.uid, client.access_key)
                await write_config(account_file, acccountinfo)
            except Exception as e:
                logger.warning(f"priconne account credential migration failed: {e}")
        # 初始化
        if group_id not in clanbattle_info:
            clanbattle_info[group_id] = ClanBattle(group_id)
        clan_info: ClanBattle = clanbattle_info[group_id]
        await clan_info.init(client, qq_id)
    except Exception as e:
        await bot.send(ev, str(e))
        return

    await _store_user_name(account_file, acccountinfo, clan_info.user_name)
    run_group[group_id] = {"self_id": ev.self_id, "qq_id": qq_id}
    await _save_run_group()
    loop_num = clan_info.loop_num
    clan_info.loop_check = time.time()
    await bot.send(ev, f"开始监控中, 可以发送【取消出刀监控】或者顶号退出\n当前监控账号：{clan_info.user_name or account_mask}\n#监控编号HN000{loop_num}")
    await _monitor_loop(bot, ev, group_id, qq_id, account_file, ev.self_id, loop_num)


# 顶号判定的服务端错误码；监控掉线日志里的 status 若对应「已在其他设备登录」，请补充到这里
KICK_STATUS_CODES = set()
KICK_KEYWORDS = ("其他设备", "已在", "顶号")
MAX_RETRY = 10


async def _median_knife_damage(clan_info, hours: int = 24):
    """全群最近 hours 小时完整刀伤害中位数（flag==0，尾刀/补偿已过滤）；无完整刀记录返回 None。"""
    try:
        return await clan_info.record.get_full_knife_median_damage(int(time.time() - hours * 3600))
    except Exception:
        return None


def _tail_compensation_seconds(remaining_hp: float, full_dmg: float) -> int | None:
    """两刀合刀时，尾刀（击杀boss那一刀）能获得的补偿秒数。

    前刀打满90s造成 full_dmg，boss剩余 H - full_dmg 由尾刀击杀。
    补偿秒数公式（与 cal 计算器一致）：e = ceil(110 - 90 * (H - d) / d)。
    """
    if not full_dmg or remaining_hp <= full_dmg or remaining_hp > 2 * full_dmg:
        return None
    e = 110 - 90 * (remaining_hp - full_dmg) / full_dmg
    return max(0, min(90, math.ceil(e)))


def _is_kicked(status, message):
    if status in KICK_STATUS_CODES:
        return True
    return any(k in str(message) for k in KICK_KEYWORDS)


async def _loop_send(bot, ev, group_id, msg):
    """监控循环内发送消息；ev 为空（bot 重启恢复）时直接发群消息。"""
    if ev is not None:
        await safe_send(bot, ev, msg)
    else:
        try:
            await bot.send_group_msg(group_id=group_id, message=msg)
        except Exception as e:
            logger.warning(f"priconne monitor send failed, group={group_id}: {e}")


async def _save_run_group():
    try:
        await write_config(run_path, run_group)
    except Exception as e:
        logger.warning(f"priconne save run_group failed: {e}")


async def _store_user_name(account_file, acccountinfo, user_name):
    """登录成功后把游戏内昵称写回账号配置，下次预登录提示可直接显示昵称。"""
    if not user_name:
        return
    try:
        acccountinfo[0] = {**acccountinfo[0], "user_name": user_name}
        await write_config(account_file, acccountinfo)
    except Exception as e:
        logger.warning(f"priconne store user_name failed: {e}")


async def _reconnect_once(group_id, qq_id, account_file):
    """用绑定账号重新登录并替换监控 client；成功返回 True。"""
    clan_info = clanbattle_info.get(group_id)
    if clan_info is None:
        return False
    try:
        acccountinfo = await load_config(account_file)
        if not acccountinfo:
            return False
        captcha_context = CaptchaContext(user_id=qq_id, group_id=group_id)
        client = await query(acccountinfo, is_force=True, captcha_context=captcha_context)
        if not await check_client(client):
            return False
        await clan_info.rebind_client(client)
        return True
    except Exception as e:
        logger.warning(f"priconne reconnect failed, group={group_id}: {e}")
        return False


async def _monitor_loop(bot, ev, group_id, qq_id, account_file, self_id, loop_num):
    """出刀监控主循环；掉线后按错误类型自动重连（顶号不重试，其他错误退避重连）。"""
    clan_info = clanbattle_info[group_id]
    while True:
        async with semaphore:
            try:
                if loop_num != clan_info.loop_num:
                    clan_info.loop_check = False
                    raise CancleError

                clan_info.loop_check = time.time()
                # 初始化
                clan_battle_top = await clan_info.get_clanbattle_top()
                clan_info.lap_num = clan_battle_top["lap_num"]
                clan_info.rank = clan_battle_top["period_rank"]

                #换面提醒
                if clan_info.period != stage_dict[lap2stage(clan_battle_top["lap_num"])]:
                    await _loop_send(bot, ev, group_id, f"阶段从{stage_dict[clan_info.period]}面到了{lap2stage(clan_battle_top['lap_num'])}面，请注意轴的切换喵")
                    clan_info.period = stage_dict[lap2stage(clan_info.lap_num)]

                change = False
                # 获取当前血量,当前王数
                for i, boss in enumerate(clan_info.boss):
                    current_boss = clan_battle_top["boss_info"][i]
                    current_hp, order, max_hp, lap_num = current_boss["current_hp"], current_boss["order_num"], current_boss["max_hp"], current_boss["lap_num"]
                    # 通知预约
                    if current_hp and (subscribe_text := await clan_info.subscribe.notify_subscribe(int(order), int(lap_num), clan_info.lap_num)):
                        clan_info.notice_subscribe.append(subscribe_text)

                    # 查看当前出刀人数
                    if fighter_num := await clan_info.refresh_fighter_num(lap_num, order):
                        clan_info.notice_fighter.append(f"{i+1}王当前有{fighter_num}人出刀")

                    # 合刀提醒：有人出刀且血量处于合刀窗口 d < H <= 2d 时提醒一次（d=全群近24h完整刀平均伤害）。
                    # 合刀 = 出补偿刀：前刀打满90s打残、尾刀（击杀boss那一刀）击杀拿补偿。
                    # H <= d 一刀直接击杀无需合刀；d < H <= 2d 两刀可收、尾刀必出补偿刀；
                    # H > 2d 两刀打不死，尾刀白打90s亏一刀，不提醒。
                    if current_hp and not boss.coop_notified:
                        if boss.fighter_num > 0:
                            d = await _median_knife_damage(clan_info)
                            if d and d < current_hp <= 2 * d:
                                comp = _tail_compensation_seconds(current_hp, d)
                                comp_text = f"，尾刀预计补偿约{comp}秒" if comp is not None else ""
                                last_kill_text = f"，上一位结算：{boss.last_kill_name}" if boss.last_kill_name else ""
                                clan_info.notice_coop.append(
                                    f"{lap_num}周目{i+1}王当前剩余{format_bignum(current_hp)}（{format_precent(current_hp / max_hp)}），"
                                    f"刀伤约{format_bignum(int(d))}/刀（中位数）{comp_text}{last_kill_text}，可以开始计划合刀了喵"
                                )
                                boss.coop_notified = True
                    elif current_hp >= max_hp:
                        boss.coop_notified = False  # 血量回满（boss刷新），重置提醒标记

                    if current_hp != boss.current_hp or lap_num != boss.lap_num:
                        change = True
                        boss.refresh(current_hp, lap_num, order, max_hp)

                await _loop_send(bot, ev, group_id, "\n".join(clan_info.notice_subscribe))
                await _loop_send(bot, ev, group_id, "\n".join(clan_info.notice_fighter))
                await _loop_send(bot, ev, group_id, "\n".join(clan_info.notice_coop))
                clan_info.notice_subscribe.clear()
                clan_info.notice_fighter.clear()
                clan_info.notice_coop.clear()

                if change:
                    notice_progress = []
                    for history in clan_battle_top["damage_history"]:
                        if history["create_time"] > clan_info.latest_time:
                            clan_info.notice_dao.append(
                                f'{history["name"]}对{history["lap_num"]}周目{history["order_num"]}王造成了{history["damage"]}点伤害。')
                            # 通知挂树，清空申请出刀
                            if history["kill"]:
                                boss_order = int(history["order_num"])
                                boss = clan_info.boss[boss_order - 1]
                                boss.last_kill_name = history["name"]
                                boss.last_kill_time = history["create_time"]
                                notice_progress.append(clan_info.general_boss())
                                try:
                                    if offtree_text := await clan_info.tree.notify_tree(boss_order):
                                        clan_info.notice_tree.append(offtree_text)
                                except Exception as e:
                                    logger.opt(exception=e).warning(
                                        f"通知下树失败，group_id={group_id}, boss={boss_order}"
                                    )
                                try:
                                    await clan_info.apply.clear_apply(boss_order)
                                except Exception as e:
                                    logger.opt(exception=e).warning(
                                        f"清空申请出刀失败，group_id={group_id}, boss={boss_order}"
                                    )

                    clan_info.refresh_latest_time(clan_battle_top)
                    await _loop_send(bot, ev, group_id, "\n".join(clan_info.notice_dao[::-1]))
                    clan_info.notice_dao.clear()
                    await _loop_send(bot, ev, group_id, "\n".join(notice_progress))
                    await _loop_send(bot, ev, group_id, "\n".join(clan_info.notice_tree))
                    clan_info.notice_tree.clear()

                clan_info.error_count = 0
                await clan_info.add_record(clan_battle_top["damage_history"], loop_num)

                # 保存最新状态快照，供离线「状态」命令展示
                if group_id in run_group:
                    run_group[group_id]["snapshot"] = {
                        "time": int(time.time()),
                        "rank": clan_info.rank,
                        "boss": clan_info.general_boss(),
                    }
                    await _save_run_group()

            except Exception as e:
                print(traceback.format_exc())
                clan_info.loop_check = False
                run_group.pop(group_id, None)
                await _save_run_group()

                if loop_num != clan_info.loop_num:
                    await _loop_send(bot, ev, group_id, f"#编号HN000{loop_num}监控已关闭")
                    return

                # 探测旧会话，区分顶号与普通错误（顶号不重试，避免登录互顶）
                reachable, status, message = await clan_info.probe_session()
                logger.warning(
                    f"priconne monitor error, group={group_id}, reachable={reachable}, "
                    f"status={status}, message={message!r}, error={e!r}"
                )
                if not reachable and _is_kicked(status, message):
                    await _loop_send(bot, ev, group_id, "当前账号已在其他设备登录，监控已退出")
                    return

                if clan_info.error_count >= MAX_RETRY:
                    clan_info.error_count = 0
                    await _loop_send(bot, ev, group_id, "超过最大重试次数，监控已退出")
                    return

                clan_info.error_count += 1
                if clan_info.error_count <= 2:
                    # 前两次先原地重试（网络抖动等瞬时错误）
                    await _loop_send(bot, ev, group_id, f"监控异常，正在重试（第{clan_info.error_count}次）")
                else:
                    if await _reconnect_once(group_id, qq_id, account_file):
                        clan_info.error_count = 0
                        await _loop_send(bot, ev, group_id, "监控已自动重连")
                    else:
                        wait = min(2 ** clan_info.error_count, 60)
                        await _loop_send(bot, ev, group_id, f"重连失败，{wait}秒后继续尝试（第{clan_info.error_count}次）")
                        await asyncio.sleep(wait)
                clan_info.loop_check = time.time()
                run_group[group_id] = {"self_id": self_id, "qq_id": qq_id}
                await _save_run_group()
        await asyncio.sleep(1)


@sv.on_fullmatch('取消出刀监控')
async def delete_monitor(bot, ev):
    group_id = ev.group_id
    qq_id = ev.user_id
    if group_id in clanbattle_info:
        clan_info: ClanBattle = clanbattle_info[group_id]
        if qq_id == clan_info.qq_id or priv.check_priv(ev, priv.ADMIN):
            clan_info.loop_num += 1
            run_group.pop(group_id, None)
            await _save_run_group()
        else:
            await bot.send(ev, "你不是监控人或者管理")
    else:
        await bot.send(ev, "本群未曾开过出刀监控")


@sv.on_fullmatch('状态')
async def daostate(bot, ev):
    group_id = ev.group_id
    if group_id in clanbattle_info and clanbattle_info[group_id].loop_check:
        clan_info: ClanBattle = clanbattle_info[group_id]
        now = time.time()
        msg = f'当前排名：{clan_info.rank}\n监控状态：'
        msg += '开启'
        member_info = await bot.get_group_member_info(group_id=group_id, user_id=clan_info.qq_id)
        msg += f'\n监控人为：{member_info["card"] or member_info["nickname"]}'
        msg += "(高占用)" if now - clan_info.loop_check > 30 else ""
        msg += "\n" + clan_info.general_boss()
        await safe_send(bot, ev, msg)

        msg = ""
        for i in range(1, 5 + 1):
            if apply_info := await clan_info.apply.get_apply(i):
                msg += f"========={i}王=========\n"
                msg += f"当前有{len(apply_info)}人申请挑战boss\n"
                for i, info in enumerate(apply_info):
                    uid, apply_time, text = info
                    member_info = await bot.get_group_member_info(group_id=group_id, user_id=uid)
                    name = member_info["card"] or member_info["nickname"]
                    msg += f"->{i+1}：{name} {text} 已过去{format_time(now - apply_time)}\n"
        await safe_send(bot, ev, msg.strip())
    else:
        snapshot = (await load_config(run_path)).get(str(group_id), {}).get("snapshot")
        if not snapshot:
            await bot.send(ev, "未查询到本群历史状态，请开启出刀监控")
            return
        latest_time = time.strftime("%Y/%m/%d-%H:%M:%S", time.localtime(snapshot["time"]))
        msg = (
            "监控状态：关闭\n"
            f"历史记录时间：{latest_time}\n"
            f"历史排名：{snapshot['rank']}\n"
            + snapshot["boss"]
        )
        await safe_send(bot, ev, msg)


@sv.on_fullmatch('boss状态')
async def bosstate(bot, ev):
    group_id = ev.group_id
    if group_id in clanbattle_info:
        clan_info : ClanBattle = clanbattle_info[group_id]
        now = time.time()
        msg = '监控状态：'
        if clan_info.loop_check:
            msg += '开启'
            member_info = await bot.get_group_member_info(group_id=group_id, user_id=clan_info.qq_id)
            msg += f'\n监控人为：{member_info["card"] or member_info["nickname"]}'
            msg += "(高占用)" if now - clan_info.loop_check > 30 else ""
        else:
            msg += '关闭'
        for i in range(1, 5 + 1):
            if apply_info := await clan_info.apply.get_apply(i):
                msg += f"\n========={i}王=========\n"
                msg += f"当前有{len(apply_info)}人申请挑战boss\n"
                for i, info in enumerate(apply_info):
                    uid, apply_time, text = info
                    member_info = await bot.get_group_member_info(group_id=group_id, user_id=uid)
                    name = member_info["card"] or member_info["nickname"]
                    msg += f"->{i+1}：{name} {text} 已过去{format_time(now - apply_time)}\n"
            if clan_info.boss[i-1].fighter_num:
                msg += f"当前挑战人数{clan_info.boss[i-1].fighter_num}\n"
        await bot.send(ev, msg.strip())
    else:
        await bot.send(ev, "未查询到本群当前进度，请开启出刀监控")


@sv.on_rex(r'^预约\s?(\d)(\s\d+)?(\s\S*)?$')
async def subscirbe(bot, ev):
    group_id = ev.group_id
    uid = ev.user_id
    match = ev['match']
    boss = int(match.group(1))
    lap = int(match.group(2)[1:]) if match.group(2) else 0

    if boss > 5 or boss < 1:
        await bot.send(ev, "不约，滚")
        return

    subDao = SubscribeDao(group_id)
    if text := match.group(3):
        text = text[1:]

    if await subDao.add_subscribe(uid, boss, lap, text if text else " "):
        await bot.send(ev, '预约成功', at_sender=True)
    else:
        await bot.send(ev, '预约失败', at_sender=True)


@sv.on_fullmatch('预约表', only_to_me=False)
async def formsubscribe(bot, ev):
    group_id = ev.group_id
    FormSubscribe = ""
    subscribers = []
    subDao = SubscribeDao(group_id)
    for boss in range(1, 5 + 1):
        if info := await subDao.get_subscriber(boss):
            for qq, lap, text in info:
                lap = f"第{lap}周目" if lap else "当前周目"
                info = await bot.get_group_member_info(group_id=ev.group_id, user_id=qq)
                name = "card" if info["card"] else "nickname"
                msg = f'{info[name]}:{text}' if text else info[name]
                msg += " " + lap
                subscribers.append(msg)
        if subscribers:
            FormSubscribe += f'\n========={boss}王=========\n' + \
                "\n".join(subscribers)
            subscribers = []

    if FormSubscribe:
        await bot.send(ev, "当前预约列表" + FormSubscribe)
    else:
        await bot.send(ev, "无人预约呢喵")


@sv.on_rex(r'^取消预约\s?(\d)$')
async def cancelsubscirbe(bot, ev):
    uid = ev.user_id
    group_id = ev.group_id
    match = ev['match']
    boss = int(match.group(1))

    if boss > 5 or boss < 1:
        await bot.send(ev, "爬爬")
        return

    for m in ev['message']:
        if m.type == 'at' and m.data['qq'] != 'all':
            if not priv.check_priv(ev, priv.ADMIN):
                await bot.send(ev, '权限不足')
                return
            else:
                uid = int(m.data['qq'])
    subDao = SubscribeDao(group_id)
    await subDao.delete_subscriber(int(uid), boss)

    await bot.send(ev, '取消成功', at_sender=True)


@sv.on_rex(r'^清空预约\s?(\d)$')
async def cleansubscirbe(bot, ev):
    group_id = ev.group_id
    if not priv.check_priv(ev, priv.ADMIN):
        await bot.send(ev, '权限不足')
    else:
        match = ev['match']
        boss = int(match.group(1))
        if boss > 5 or boss < 1:
            await bot.send(ev, "爬爬")
            return
        subDao = SubscribeDao(group_id)
        await subDao.clear_subscriber(boss)
        await bot.send(ev, '清除成功', at_sender=True)


@sv.on_fullmatch(('sl', 'SL', "Sl"))
async def addsl(bot, ev):
    group_id = ev.group_id
    sl_dao = SLDao(group_id)
    result = await sl_dao.add_sl(ev.user_id)
    if result == 0:
        await bot.send(ev, 'SL已记录', at_sender=True)
    elif result == 1:
        await bot.send(ev, '今天已经SL过了', at_sender=True)
    else:
        await bot.send(ev, '数据库错误 请查看log')


@sv.on_fullmatch(('sl?', 'SL?', 'sl？', 'SL？'))
async def issl(bot, ev):
    group_id = ev.group_id
    sl_dao = SLDao(group_id)
    result = await sl_dao.check_sl(ev.user_id)
    if result == 0:
        await bot.send(ev, '今天还没有使用过SL', at_sender=True)
    elif result == 1:
        await bot.send(ev, '今天已经SL过了', at_sender=True)
    else:
        await bot.send(ev, '数据库错误 请查看log')


@sv.on_rex(r"^(上|挂)树\s?(\d)\s?(.+)?$")
async def climbtree(bot, ev):
    group_id = ev.group_id
    uid = ev.user_id
    match = ev['match']
    boss = match.group(2)
    text = match.group(3)

    treeDao = TreeDao(group_id)

    if await treeDao.add_tree(uid, boss, text if text else " "):
        await bot.send(ev, '上树成功', at_sender=True)
    else:
        await bot.send(ev, '上树失败', at_sender=True)


@sv.on_fullmatch('下树')
async def offtree(bot, ev):
    uid = ev.user_id
    group_id = ev.group_id

    treeDao = TreeDao(group_id)
    await treeDao.delete_tree(uid)

    await bot.send(ev, '下树成功', at_sender=True)


@sv.on_fullmatch('查树')
async def checktree(bot, ev):
    group_id = ev.group_id
    reply = ""
    treeDao = TreeDao(group_id)
    for i in range(5):
        if info := await treeDao.get_tree(i+1):
            reply += f'{i+1}王树上目前有{len(info)}人\n'
            now = time.time()
            for i, info in enumerate(info):
                uid, tree_time, text = info
                info = await bot.get_group_member_info(group_id=ev.group_id, user_id=uid)
                name = "card" if info["card"] else "nickname"
                reply += f"->{i+1}：{info[name]} {text} 已过去{format_time(now - tree_time)}\n"
    if reply:
        await bot.send(ev, reply)
    else:
        await bot.send(ev, "目前树上空空如也")


@sv.on_rex(r'^(?:申请出刀|进|打)\s?(\d)\s?(\S+)?$')
async def apply(bot, ev):
    group_id = ev.group_id
    at = re.search(r'\[CQ:at,qq=(\d*)]', str(ev.message))
    uid = at.group(1) if at else ev.user_id
    match = ev['match']

    applyDao = ApplyDao(group_id)
    boss = match.group(1)
    text = match.group(2)

    if await applyDao.add_apply(uid, boss, text if text else " "):
        await bot.send(ev, "申请成功", at_sender=True)
    else:
        await bot.send(ev, "申请失败", at_sender=True)


@sv.on_rex(r"^(?:取消申请|不进了|不打了)$")
async def checktree(bot, ev):
    group_id = ev.group_id
    uid = ev.user_id
    if at := re.search(r'\[CQ:at,qq=(\d*)]', str(ev.message)):
        if not priv.check_priv(ev, priv.ADMIN):
            await bot.send(ev, '权限不足')
            return
        uid = at.group(1)

    applyDao = ApplyDao(group_id)
    await applyDao.delete_apply(int(uid))

    await bot.send(ev, '取消成功', at_sender=True)


@sv.on_fullmatch('今日出刀')
async def today_state(bot, ev):
    group_id = ev.group_id
    db = RecordDao(group_id)
    data = await db.get_day_rcords(int(time.time()))
    if not data:
        await bot.send(ev, "数据库为空，请确保开启出刀监控")
    players = day_report(data)
    result = await get_stat(players, group_id)
    await bot.send(ev, result)


@sv.on_fullmatch('昨日出刀')
async def yesterday_state(bot, ev):
    group_id = ev.group_id
    db = RecordDao(group_id)
    data = await db.get_day_rcords(int(time.time()) - 3600 * 24)
    if not data:
        await bot.send(ev, "数据库为空，请确保开启出刀监控")
    players = day_report(data)
    result = await get_stat(players, group_id)
    await bot.send(ev, result)


@sv.on_fullmatch('回归性原理')
async def bigfun_check(bot, ev):
    try:
        msg = await bigfun_fix(ev.group_id, RecordDao(ev.group_id))
    except Exception as e:
        msg = str(e)
    await bot.send(ev, msg)


@sv.on_fullmatch('启用肃正协议')
async def kill_all(bot, ev):
    group_id = ev.group_id
    await clear_group_data(group_id)
    await bot.send(ev, "[WARNING]肃正协议将清理一切事物（不分敌我），期间出现任何报错均为正常现象，事后请重新开启出刀监控")


@sv.on_fullmatch('当前战报')
async def get_report(bot, ev):
    group_id = ev.group_id
    db = RecordDao(group_id)
    data = await db.get_all_records()
    if not data:
        await bot.send(ev, "数据库为空，请确保开启出刀监控")
        return
    max_dao = await db.get_max_dao()
    players, all_damage, all_score = clanbattle_report(data, max_dao)
    img = await get_cbreport(players, all_damage, all_score)
    await bot.send(ev, img)


@sv.on_prefix('今日战报', '昨日战报', "我的战报")
async def player_report(bot, ev):
    name = ev.message.extract_plain_text().strip()
    if (preid := ev.prefix[:2]) == "今日":
        day = 0
    elif preid == "昨日":
        day = 1
    else:
        day = 5
    group_id = ev.group_id
    db = RecordDao(group_id)
    data = await db.get_player_records(name, day)
    if not data:
        await bot.send(ev, "数据库为空，请确保开启出刀监控或使用正确的角色名")
        return
    img = await get_plyerreport(data)
    await bot.send(ev, img)


@sv.on_prefix('出刀详情')
async def player_report(bot, ev):
    if id := ev.message.extract_plain_text().strip():
        if not id.isdigit():
            await bot.send(ev, "请输入正确的出刀编号")
        else:
            detail = RecordDao(ev.group_id)
            info = await detail.get_history(id)
            if info:
                await bot.send(ev, await dao_detial(info))
            else:
                await bot.send(ev, "请检查你的出刀编号是否正确。")

@sv.on_rex(r'修正出刀\s?(\d+)\s?(完整刀|尾刀|补偿)?')
async def correct_dao(bot, ev):
    records = RecordDao(ev.group_id)
    info = ev["match"]
    dao_id = info.group(1)
    dao = info.group(2)
    item = 0 if dao == "完整刀" else 1 if dao == "尾刀" else 0.5
    if await records.correct_dao(dao_id, item):
        await bot.send(ev, "修改成功")
    else:
        await bot.send(ev, "请检查你输入了正确的出刀编号")
    
@sv.on_fullmatch('催刀')
async def nei_gui(bot, ev):
    group_id = ev.group_id
    db = RecordDao(group_id)
    data = await db.get_day_rcords(int(time.time()))
    if not data:
        await bot.send(ev, "数据库为空，请确保开启出刀监控或使用“回归性原理”进行修正")
    else:
        players = day_report(data)
        result = await cuidao(players, group_id)
        await bot.send(ev, result)

@sv.on_fullmatch('会战KPI', '会战kpi')
async def get_kpi(bot, ev):
    group_id = ev.group_id
    db = RecordDao(group_id)
    data = await db.get_all_records()
    if not data:
        await bot.send(ev, "数据库为空，请确保开启出刀监控或使用“回归性原理”进行修正")
    else:
        special = await load_config(os.path.join(clan_path, f'{group_id}', "clanbattle.json"))
        special = {} if not special else special["kpi"] if "kpi" in special else {}
        players = kpi_report(data, special)
        img = await get_kpireport(players)
        await bot.send(ev, img)


@sv.on_prefix("kpi调整")
async def correct_kpi(bot, ev):
    if not priv.check_priv(ev, priv.ADMIN):
        await bot.send(ev, '权限不足')
        return
    try:
        info = ev.message.extract_plain_text().strip().split()
        id = info[0]
        score = int(info[1])
        config_file = os.path.join(
            clan_path, f'{ev.group_id}', "clanbattle.json")
        if not (config := await load_config(config_file)):
            config = {}
        if "kpi" not in config:
            config["kpi"] = {}
        config["kpi"][id] = score
        await write_config(config_file, config)
        await bot.send(ev, "设置成功")
    except:
        await bot.send(ev, "设置失败，一定是你输入了奇怪的东西，爬爬")


@sv.on_fullmatch("清空kpi", "清空KPI")
async def clean_kpi(bot, ev):
    try:
        config_file = os.path.join(clan_path, f'{ev.group_id}', "clanbattle.json")
        config = await load_config(config_file)
        del config["kpi"]
        await write_config(config_file, config)
        await bot.send(ev, "清空成功")
    except:
        await bot.send(ev, "清空失败，请检查你是否设置过kpi")


@sv.on_prefix("删除kpi", "删除KPI")
async def del_kpi(bot, ev):
    try:
        id = ev.message.extract_plain_text().strip()
        config_file = os.path.join(
            clan_path, f'{ev.group_id}', "clanbattle.json")
        config = await load_config(config_file)
        del config["kpi"][id]
        await write_config(config_file, config)
        await bot.send(ev, "删除成功")
    except:
        await bot.send(ev, "删除失败，请检查此角色是否设置过kpi")

@sv.scheduled_job('cron', hour='4', minute='59', jitter=50)
async def init_cb():
    bot = get_bot()
    group_list = await bot.get_group_list()
    group_list = [group['group_id'] for group in group_list]
    for group_id in group_list:
        for db in (RecordDao(group_id), SubscribeDao(group_id), SLDao(group_id), ApplyDao(group_id), TreeDao(group_id)):
            await db.refresh()

@sv.on_fullmatch("缓存运行群")
async def resatrt_remind(bot, ev):
    await write_config(run_path, run_group)
    await bot.send(ev, "成功")

@sv.on_fullmatch("提醒掉线")
async def resatrt_remind(bot, ev):
    bot = get_bot()
    for gid, info in (await load_config(run_path)).items():
        self_id = info.get("self_id") if isinstance(info, dict) else info
        try:
            await bot.send_group_msg(self_id=self_id, group_id=gid, message="遭遇神秘的桥本环奈偷袭，请检查出刀监控")
        except Exception as e:
            pass
    await write_config(run_path, {})

@sv.on_prefix("cal", "合刀", "尾刀计算")
async def pcr_calculator_interface(bot, ev):
    msg = ev.message.extract_plain_text().strip()
    if len(msg) == 0:
        await bot.send(ev, "什么都不发，你让我算啥呢？")
        return
    await bot.send(ev, calculator(msg).ToString(sep="\n\n"))

@sv.on_command('update_device_id', aliases=('自动报刀换设备id', '自动报刀更新设备id'), only_to_me=False)
async def update_device_id(session: NoticeSession):
    init_device_id(clear_id = True)
    await session.send('自动报刀更新设备id成功！重启bot生效新设备id')


_resumed = False


@get_driver().on_bot_connect
async def resume_monitors(bot):
    """bot 启动后，恢复 rungroup.json 中持久化的监控。"""
    global _resumed
    if _resumed:
        return
    _resumed = True
    for gid, info in (await load_config(run_path)).items():
        if not isinstance(info, dict) or not info.get("qq_id"):
            continue  # 旧格式无 qq_id，无法自动登录，跳过
        gid = int(gid)
        qq_id = int(info["qq_id"])
        account_file = os.path.join(DATA_PATH, 'account', f'{qq_id}.json')
        if gid in clanbattle_info and clanbattle_info[gid].loop_check:
            continue  # 已有活跃监控
        try:
            acccountinfo = await load_config(account_file)
            if not acccountinfo:
                logger.warning(f"priconne auto resume skipped, group={gid}: account file missing")
                continue
            captcha_context = CaptchaContext(user_id=qq_id, group_id=gid)
            client = await query(acccountinfo, captcha_context=captcha_context)
            if not await check_client(client):
                raise Exception("登录异常，请重试")
            if gid not in clanbattle_info:
                clanbattle_info[gid] = ClanBattle(gid)
            clan_info = clanbattle_info[gid]
            await clan_info.init(client, qq_id)
            await _store_user_name(account_file, acccountinfo, clan_info.user_name)
            loop_num = clan_info.loop_num
            clan_info.loop_check = time.time()
            run_group[gid] = {"self_id": info.get("self_id"), "qq_id": qq_id}
            await _save_run_group()
            await _loop_send(bot, None, gid, f"出刀监控已自动恢复（监控账号：{clan_info.user_name or qq_id}）")
            asyncio.create_task(_monitor_loop(bot, None, gid, qq_id, account_file, info.get("self_id"), loop_num))
        except Exception as e:
            logger.warning(f"priconne auto resume failed, group={gid}: {e}")


@sv.scheduled_job('cron', hour='5', minute='0', timezone=ZoneInfo("Asia/Shanghai"), jitter=300)
async def daily_rank_broadcast():
    """每天 05:00 向运行监控的群播报当前会战排名与 boss 进度。"""
    bot = get_bot()
    now = time.time()
    for group_id, clan_info in list(clanbattle_info.items()):
        if not clan_info.loop_check:
            continue
        if now - clan_info.loop_check > 120:
            continue  # 监控已掉线，不播报
        info = run_group.get(group_id)
        self_id = info.get("self_id") if isinstance(info, dict) else None
        msg = f"当前排名：{clan_info.rank}\n" + clan_info.general_boss()
        try:
            await bot.send_group_msg(self_id=self_id, group_id=group_id, message=msg)
        except Exception as e:
            logger.warning(f"priconne daily rank broadcast failed, group={group_id}: {e}")
