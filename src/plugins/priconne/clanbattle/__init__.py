import re
import os
import math
import traceback
import time
import asyncio
from datetime import timedelta

from zoneinfo import ZoneInfo

from nonebot import get_bot, get_driver, logger
from nonebot.permission import SUPERUSER
from src.plugins.platform_adapter.sender import send_group

from ..captcha import CaptchaContext
from ..compat import Service, priv, on_startup, MessageSegment
from ..compat.typing import NoticeSession
from ..credentials import build_stored_account, should_update_stored_account
from ..login import query
from ..util.tools import load_config, write_config, safe_send, check_client, DATA_PATH, stage_dict
from .base import *
from .model import ClanBattle
from .kpi import kpi_report
from .sql import SubscribeDao, RecordDao, SLDao, TreeDao, ApplyDao, clear_group_data
from .pcr_calculator import calculator
from .reports import (
    boss_snapshot, snapshot_bosses, daily_report, preference_report, report_status,
    control_report, parse_declaration_input, encode_declaration, declaration_text, member_roster, status_report,
    registration_report,
)
from .sql import pcr_date
from .period import get_period
from .dispatch import build_dispatch, activity_report, coordination_reports, register_member_link
from .review import build_review, render_review, REVIEW_PAGES
from .summary import send_summary, summary_due
from .settlement import battle_notice

_member_link_lock = asyncio.Lock()

from ..pcrclient import init_device_id, ApiException, RETRYABLE_SERVER_ERROR_STATUS, _is_network_error as _client_network_error

help_text = '''
查看进度
【状态】监控人、五王血条、现场人数与当前提示
【boss状态】状态图及申请、挂树明细
【今日刀表 / 今日出刀】按刀数分组查看成员与人数
【会战指挥台 / BOSS推进参考】排刀、合刀候选与时段规划
【出刀时段】习惯时段与本期可能活跃成员
【催刀】按已保存记录提醒，需核验实际可用刀

出刀登记（示例中的空格需保留）
【申请出刀 3 完整 1000万】申报预计伤害，可追加留言
【申请出刀 3 补偿60秒 450万】申报补偿刀；血量变化后重新申请
【申请出刀 3 留言】【取消申请】普通申请与取消
【预约 3 [周目] [留言]】周目、留言可省略
【预约表】【取消预约 王号】查看与取消预约
【挂树 3】【查树】【下树】登记、查看与取消挂树
【sl】【sl?】记录与查询今日SL
【登记会战成员 游戏ID】【取消会战成员登记】关联QQ与游戏ID；管理员可@成员代操作

战报与复盘
【会战复盘 / 会战总结】本期五张复盘图
【刀伤分布】五王分布；【刀伤分档】成员分档
【当前战报】【昨日出刀】本期汇总与昨日记录
【我的战报 游戏名称】【今日战报 游戏名称】【昨日战报 游戏名称】个人战报
【出刀详情 出刀编号】编号可从个人战报查看

监控与管理
【出刀监控】使用已绑定账号开启监控
【取消出刀监控】监控人或管理员关闭监控
【清空预约 王号】管理员清理预约
【修正出刀 编号 完整刀/尾刀/补偿】修正刀型
【启用肃正协议】危险操作：清空群会战数据
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
    _set_monitor_registered(group_id, ev.self_id, qq_id)
    await _save_run_group()
    loop_num = clan_info.loop_num
    clan_info.loop_check = time.time()
    await bot.send(ev, f"开始监控中, 可以发送【取消出刀监控】或者顶号退出\n当前监控账号：{clan_info.user_name or account_mask}\n#监控编号HN000{loop_num}")
    await _monitor_loop(bot, ev, group_id, qq_id, account_file, ev.self_id, loop_num)


# 服务端 server_error.status 映射到 NetworkUI.eServerErrorAct 枚举。
# native 反汇编证实：顶号/会话失效走 status=3 (ReturnTitle)。
# 保守先只把 3 视为终止态；完整终止集是 {0,1,2,3,999999}，可重试集是 {4,5,6,7,8}。
TERMINAL_ERROR_ACTS = {3}
MAX_RETRY = 10


def _terminal_status_reason(status, message):
    """若 server_error.status 表示不可恢复错误，返回退出原因；否则返回 None（走重试）。"""
    if status in TERMINAL_ERROR_ACTS:
        return "监控账号会话已失效（顶号或掉线，需回到标题重登），监控已退出，请重新开启"
    return None


def _is_network_error(e):
    return _client_network_error(e)


def _is_kicked(status, message):
    """兼容旧服务端关键字兜底（实际已由 status 判定主导）。"""
    if status in TERMINAL_ERROR_ACTS:
        return True
    return any(k in str(message) for k in KICK_KEYWORDS)


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
    temp_path = f"{run_path}.tmp"
    try:
        await write_config(temp_path, run_group)
        os.replace(temp_path, run_path)
        return True
    except Exception as e:
        logger.warning(f"priconne save run_group failed: {e}")
        return False


def _set_monitor_registered(group_id, self_id, qq_id):
    """保留监控恢复所需字段；适用于正常运行和临时重连状态。"""
    info = run_group.get(group_id)
    if not isinstance(info, dict):
        info = {}
    run_group[group_id] = {
        **info,
        "self_id": self_id,
        "qq_id": qq_id,
    }
    event = getattr(clanbattle_info.get(group_id), "event", None)
    if event is not None and event.active(time.time()) and self_id is not None:
        run_group[group_id]["summary"] = {"period_id": event.id, "self_id": str(self_id)}


def _set_monitor_stopped(group_id):
    """清除监控运行字段；存在历史快照时保留群记录。"""
    info = run_group.get(group_id)
    snapshot = info.get("snapshot") if isinstance(info, dict) else None
    summary = info.get("summary") if isinstance(info, dict) else None
    if summary:
        run_group[group_id] = {"summary": summary, **({"snapshot": snapshot} if snapshot else {})}
        return
    if snapshot:
        run_group[group_id] = {"snapshot": snapshot}
    else:
        run_group.pop(group_id, None)


def _invalidate_monitor_loop(group_id):
    """使当前监控循环失效，并立即反映为进程内离线状态。"""
    clan_info = clanbattle_info.get(group_id)
    if clan_info is not None:
        clan_info.loop_num += 1
        clan_info.loop_check = False


def _set_monitor_snapshot(group_id, snapshot):
    """保存最近状态；只为当前或曾经登记过的群创建快照。"""
    info = run_group.get(group_id)
    if not isinstance(info, dict):
        return False
    run_group[group_id] = {**info, "snapshot": snapshot}
    return True


def _restore_run_group(saved):
    """从 JSON 数据恢复全部群记录，包含仅有历史快照的已停止监控群。"""
    run_group.clear()
    if not isinstance(saved, dict):
        return
    for group_id, info in saved.items():
        try:
            normalized_group_id = int(group_id)
        except (TypeError, ValueError):
            logger.warning(f"priconne run_group skipped invalid group id: {group_id!r}")
            continue
        if not isinstance(info, dict):
            logger.warning(
                f"priconne run_group skipped non-object entry, group={normalized_group_id}"
            )
            continue
        restored = info.copy()
        if "qq_id" in restored:
            try:
                restored["qq_id"] = int(restored["qq_id"])
            except (TypeError, ValueError):
                logger.warning(
                    f"priconne run_group skipped invalid qq_id, group={normalized_group_id}"
                )
                continue
        snapshot = restored.get("snapshot")
        if snapshot is not None:
            required_snapshot_fields = {"time", "rank", "boss"}
            if (
                not isinstance(snapshot, dict)
                or not required_snapshot_fields.issubset(snapshot)
                or not isinstance(snapshot["time"], (int, float))
                or not isinstance(snapshot["rank"], int)
                or not isinstance(snapshot["boss"], str)
            ):
                logger.warning(
                    f"priconne run_group skipped invalid snapshot, group={normalized_group_id}"
                )
                continue
        summary = restored.get("summary")
        if summary is not None and (
            not isinstance(summary, dict) or type(summary.get("period_id")) is not int
            or summary["period_id"] <= 0 or not isinstance(summary.get("self_id"), str)
            or not summary["self_id"]
        ):
            restored.pop("summary", None)
        if "qq_id" not in restored and snapshot is None and not restored.get("summary"):
            logger.warning(
                f"priconne run_group skipped empty entry, group={normalized_group_id}"
            )
            continue
        run_group[normalized_group_id] = restored


async def _is_superuser(bot, ev):
    """在 legacy 兼容层中复用 NoneBot 原生 SUPERUSER 权限规则。"""
    raw_bot = getattr(bot, "_bot", bot)
    raw_event = getattr(ev, "_event", ev)
    return await SUPERUSER(raw_bot, raw_event)


async def _stop_if_loop_invalid(bot, ev, group_id, clan_info, loop_num):
    """异步等待后检查旧循环是否已被取消；已取消则完成离线持久化。"""
    if loop_num == clan_info.loop_num:
        return False
    clan_info.loop_check = False
    _set_monitor_stopped(group_id)
    await _save_run_group()
    await _loop_send(bot, ev, group_id, f"#编号HN000{loop_num}监控已关闭")
    return True


async def _resume_monitor_if_current(
    clan_info,
    group_id,
    self_id,
    qq_id,
    loop_num,
):
    """仅允许仍有效的循环恢复心跳和持久化注册字段。"""
    if loop_num != clan_info.loop_num:
        return False
    clan_info.loop_check = time.time()
    _set_monitor_registered(group_id, self_id, qq_id)
    await _save_run_group()
    return True


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
                state_updated_at = int(time.time())
                changed_event = clan_info.event is None or clan_info.event.id != clan_battle_top["clan_battle_id"]
                await clan_info.bind_period(clan_battle_top["clan_battle_id"])
                if changed_event:
                    await clan_info.save_member(os.path.join(clan_path, str(group_id), "clanbattle.json"))
                    _set_monitor_registered(group_id, self_id, qq_id)
                    await _save_run_group()
                if not clan_info.event.active(state_updated_at):
                    clan_info.loop_check = False
                    await asyncio.sleep(30)
                    continue
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

                record_sync_ok = await clan_info.add_record(
                    clan_battle_top["damage_history"], loop_num, clan_battle_top["boss_info"])
                if loop_num != clan_info.loop_num:
                    raise CancleError
                if change:
                    notice_progress = []
                    for history in clan_battle_top["damage_history"]:
                        if history["create_time"] > clan_info.latest_time:
                            key = (str(history.get("viewer_id")), history["lap_num"], str(history["order_num"]), history["create_time"])
                            clan_info.notice_dao.append(battle_notice(history, clan_info.settlements.get(key)))
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

                bosses = boss_snapshot(clan_info, time.time())
                clan_info.error_count = 0
                if loop_num != clan_info.loop_num:
                    raise CancleError
                previous = run_group.get(group_id, {}).get("snapshot", {})
                if previous.get("clan_battle_id") != clan_info.event.id:
                    previous = {}
                records_synced_at = (
                    int(time.time()) if record_sync_ok is True
                    else previous.get("records_synced_at", 0)
                )

                # 保存最新状态快照，供离线「状态」命令展示
                if _set_monitor_snapshot(
                    group_id,
                    {
                        "time": state_updated_at,
                        "rank": clan_info.rank,
                        "boss": clan_info.general_boss(),
                        "bosses": bosses,
                        "clan_battle_id": clan_battle_top.get("clan_battle_id", getattr(clan_info, "clan_battle_id", 0)),
                        "battle_start": clan_info.event.start,
                        "battle_end": clan_info.event.end - 1,
                        "records_synced_at": records_synced_at,
                        "record_sync_ok": record_sync_ok is True,
                        "monitor_qq_id": qq_id,
                    },
                ):
                    await _save_run_group()

            except Exception as e:
                print(traceback.format_exc())
                clan_info.loop_check = False
                if await _stop_if_loop_invalid(bot, ev, group_id, clan_info, loop_num):
                    return
                # 临时异常期间保留运行字段，使进程或容器重启后仍可自动恢复。
                _set_monitor_registered(group_id, self_id, qq_id)
                await _save_run_group()

                # 探测旧会话，区分顶号/终止态、本地网络波动与普通错误
                reachable, status, message = await clan_info.probe_session()
                if await _stop_if_loop_invalid(bot, ev, group_id, clan_info, loop_num):
                    return
                logger.warning(
                    f"priconne monitor error, group={group_id}, reachable={reachable}, "
                    f"status={status}, message={message!r}, error={e!r}"
                )
                original_status = e.code if isinstance(e, ApiException) else None
                reason = _terminal_status_reason(original_status, str(e))
                if reason or (not reachable and (reason := _terminal_status_reason(status, message))):
                    _set_monitor_stopped(group_id)
                    await _save_run_group()
                    await _loop_send(bot, ev, group_id, reason)
                    return

                # 后续探测成功不能抹掉本次临时故障，也无需重新登录。
                if (_is_network_error(e) or original_status in RETRYABLE_SERVER_ERROR_STATUS
                        or (not reachable and status in RETRYABLE_SERVER_ERROR_STATUS)):
                    clan_info.error_count += 1
                    wait = 2 ** min(clan_info.error_count, 7)
                    wait = min(wait, 120)
                    logger.warning(f"priconne monitor backoff: group={group_id}, wait={wait}s, attempt={clan_info.error_count}")
                    if await _stop_if_loop_invalid(bot, ev, group_id, clan_info, loop_num):
                        return
                    await asyncio.sleep(wait)
                    if await _stop_if_loop_invalid(bot, ev, group_id, clan_info, loop_num):
                        return
                    await _resume_monitor_if_current(
                        clan_info, group_id, self_id, qq_id, loop_num
                    )
                    continue

                if clan_info.error_count >= MAX_RETRY:
                    clan_info.error_count = 0
                    _set_monitor_stopped(group_id)
                    await _save_run_group()
                    await _loop_send(bot, ev, group_id, "超过最大重试次数，监控已退出")
                    return

                clan_info.error_count += 1
                if clan_info.error_count <= 2:
                    # 前两次先原地重试（网络抖动等瞬时错误）
                    await _loop_send(bot, ev, group_id, f"监控异常，正在重试（第{clan_info.error_count}次）")
                    if await _stop_if_loop_invalid(bot, ev, group_id, clan_info, loop_num):
                        return
                else:
                    if await _reconnect_once(group_id, qq_id, account_file):
                        if await _stop_if_loop_invalid(bot, ev, group_id, clan_info, loop_num):
                            return
                        clan_info.error_count = 0
                        await _loop_send(bot, ev, group_id, "监控已自动重连")
                        if await _stop_if_loop_invalid(bot, ev, group_id, clan_info, loop_num):
                            return
                    else:
                        if await _stop_if_loop_invalid(bot, ev, group_id, clan_info, loop_num):
                            return
                        wait = min(2 ** clan_info.error_count, 60)
                        await _loop_send(bot, ev, group_id, f"重连失败，{wait}秒后继续尝试（第{clan_info.error_count}次）")
                        if await _stop_if_loop_invalid(bot, ev, group_id, clan_info, loop_num):
                            return
                        await asyncio.sleep(wait)
                        if await _stop_if_loop_invalid(bot, ev, group_id, clan_info, loop_num):
                            return
                await _resume_monitor_if_current(
                    clan_info, group_id, self_id, qq_id, loop_num
                )
        await asyncio.sleep(1)


@sv.on_fullmatch('取消出刀监控')
async def delete_monitor(bot, ev):
    group_id = ev.group_id
    qq_id = ev.user_id
    if group_id in clanbattle_info:
        clan_info: ClanBattle = clanbattle_info[group_id]
        if qq_id == clan_info.qq_id or priv.check_priv(ev, priv.ADMIN):
            _invalidate_monitor_loop(group_id)
            _set_monitor_stopped(group_id)
            await _save_run_group()
        else:
            await bot.send(ev, "你不是监控人或者管理")
    else:
        await bot.send(ev, "本群未曾开过出刀监控")


async def _send_battle_status(bot, ev, details=False):
    if not getattr(ev, "group_id", None):
        await bot.send(ev, "请在公会群中查看状态。")
        return
    period = await _event_period(bot, ev)
    if period is None:
        return
    now = int(time.time())
    snapshot, online = await _report_context(ev.group_id, now, period)
    bosses = snapshot_bosses(snapshot)
    queues, names, records = {}, {}, []
    clan = clanbattle_info.get(ev.group_id)
    if online and bosses and getattr(getattr(clan, "event", None), "id", None) == period.id:
        config = await load_config(os.path.join(clan_path, str(ev.group_id), "clanbattle.json")) or {}
        if config.get("clan_battle_id") == period.id:
            queues, names = await _report_queues(bot, ev.group_id, bosses, member_names=details)
            try:
                records = await RecordDao(ev.group_id).get_report_records(period.start, min(period.end, now + 1))
            except Exception as error:
                logger.opt(exception=error).warning(f"状态图伤害样本读取失败，group={ev.group_id}")
    qq = getattr(clan, "qq_id", None) if getattr(getattr(clan, "event", None), "id", None) == period.id else None
    qq = qq or snapshot.get("monitor_qq_id")
    monitor_name = None
    if type(qq) is int and qq > 0:
        try:
            member = await bot.get_group_member_info(group_id=ev.group_id, user_id=qq)
            name = member.get("card") or member.get("nickname")
            monitor_name = f"{name} (QQ {qq})" if name else f"QQ {qq}"
        except Exception:
            monitor_name = f"QQ {qq}"
    now = int(time.time())
    snapshot, online = await _report_context(ev.group_id, now, period)
    if not online or clan is not clanbattle_info.get(ev.group_id):
        queues, names = {}, {}
    if clan is not clanbattle_info.get(ev.group_id):
        monitor_name = None
    image = await asyncio.to_thread(status_report, snapshot, online, now, period, ev.group_id,
                                    queues, names, details, records, monitor_name)
    await bot.send(ev, image)


@sv.on_fullmatch('状态')
async def daostate(bot, ev):
    await _send_battle_status(bot, ev)


@sv.on_fullmatch('boss状态')
async def bosstate(bot, ev):
    await _send_battle_status(bot, ev, details=True)


@sv.on_rex(r'^预约\s?(\d)(\s\d+)?(\s\S*)?$')
async def subscirbe(bot, ev):
    if await _registration_period(bot, ev) is None:
        return
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
    await _send_registration_list(bot, ev, "subscribe")


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
    if await _registration_period(bot, ev) is None:
        return
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
async def tree_list(bot, ev):
    await _send_registration_list(bot, ev, "tree")


async def _send_registration_list(bot, ev, kind):
    if not getattr(ev, "group_id", None):
        await bot.send(ev, "请在公会群中查看登记。")
        return
    period = await _event_period(bot, ev)
    if period is None:
        return
    group_id, now = ev.group_id, int(time.time())
    path = os.path.join(clan_path, str(group_id), "clanbattle.json")
    config = await load_config(path) or {}
    bound = config.get("clan_battle_id") == period.id
    entries, names = {}, {}
    if period.active(now) and bound:
        dao = SubscribeDao(group_id) if kind == "subscribe" else TreeDao(group_id)
        for order in range(1, 6):
            rows = await (dao.get_subscriber(order) if kind == "subscribe" else dao.get_tree(order))
            entries[order] = [row for row in rows if kind == "subscribe" or period.start <= row[1] <= now]
        for uid in {row[0] for rows in entries.values() for row in rows}:
            try:
                member = await bot.get_group_member_info(group_id=group_id, user_id=uid)
                names[uid] = member.get("card") or member.get("nickname") or f"QQ {uid}"
            except Exception:
                names[uid] = f"QQ {uid}"
        # 名称查询期间可能换期，展示前重新核验绑定与活动边界。
        now = int(time.time())
        config = await load_config(path) or {}
        bound = config.get("clan_battle_id") == period.id
        if not period.active(now) or not bound:
            entries, names = {}, {}
    snapshot, online = await _report_context(group_id, now, period)
    image = await asyncio.to_thread(registration_report, kind, entries, names, now, period,
                                    group_id, snapshot, online, bound)
    await bot.send(ev, image)


@sv.on_rex(r'^(?:申请出刀|进|打)\s*(\d)\s*(.*)$')
async def apply(bot, ev):
    if not getattr(ev, "group_id", None):
        await bot.send(ev, "请在公会群中申请出刀。")
        return
    group_id = ev.group_id
    at = re.search(r'\[CQ:at,qq=(\d*)]', str(ev.message))
    uid = int(at.group(1)) if at else ev.user_id
    match = ev['match']

    applyDao = ApplyDao(group_id)
    boss = int(match.group(1))
    text = match.group(2).strip()
    if not 1 <= boss <= 5:
        await bot.send(ev, "BOSS编号须为1–5。")
        return
    try:
        declared = parse_declaration_input(text)
    except ValueError as error:
        await bot.send(ev, str(error))
        return
    if declared:
        if uid != ev.user_id and not priv.check_priv(ev, priv.ADMIN):
            await bot.send(ev, "代他人申报伤害需要管理员权限。")
            return
        now = int(time.time())
        period = await _event_period(bot, ev)
        if period is None:
            return
        snapshot, online = await _report_context(group_id, now, period)
        bosses = snapshot_bosses(snapshot)
        event = snapshot.get("clan_battle_id")
        if not online or bosses is None or type(event) is not int or event <= 0:
            await bot.send(ev, "伤害申报需要最新会战状态，请开启出刀监控并等待刷新。普通留言申请仍可使用。")
            return
        target = bosses[boss - 1]
        if not target["available"] or not target["current_hp"]:
            await bot.send(ev, "该王当前无法挑战，请使用预约登记后续安排。")
            return
        declared.update(event=event, lap=target["lap_num"], hp=target["current_hp"])
        text = encode_declaration(declared)

    period = await _registration_period(bot, ev)
    if period is None:
        return
    if await applyDao.add_apply(uid, boss, text if text else " "):
        response = "申请成功"
        if declared:
            response += f"｜{boss}王 {declaration_text(text)}\n血量变化或超过30分钟后请重新申请；多王申报需取消后确定目标。"
        await bot.send(ev, MessageSegment.text(response), at_sender=True)
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


async def _event_period(bot, ev):
    try:
        return await get_period()
    except ValueError as error:
        await bot.send(ev, str(error))
        return None


async def _registration_period(bot, ev):
    period = await _event_period(bot, ev)
    if period is None:
        return None
    if not period.active(time.time()):
        await bot.send(ev, period.label(time.time()) + "\n当前不在出刀活动时间内。")
        return None
    config = await load_config(os.path.join(clan_path, str(ev.group_id), "clanbattle.json"))
    if not config or config.get("clan_battle_id") != period.id:
        await bot.send(ev, "登记尚未绑定本期会战，请开启出刀监控刷新；上一期登记不参与调度。")
        return None
    return period


async def _report_context(group_id, now, period=None):
    info = run_group.get(group_id)
    if not isinstance(info, dict) or not isinstance(info.get("snapshot"), dict):
        saved = await load_config(run_path)
        info = saved.get(str(group_id), {}) if isinstance(saved, dict) else {}
    if not isinstance(info, dict):
        info = {}
    snapshot = info.get("snapshot", {})
    if not isinstance(snapshot, dict):
        snapshot = {}
    clan_info = clanbattle_info.get(group_id)
    updated = snapshot.get("time", 0)
    if period is not None:
        if (type(updated) not in (int, float) or not period.start <= updated < period.end
                or snapshot.get("clan_battle_id") not in (None, period.id)):
            return {}, False
    online = bool(
        (period is None or period.active(now))
        and clan_info and clan_info.loop_check and isinstance(updated, (int, float))
        and 0 <= now - updated <= 120
    )
    return snapshot, online


async def _report_queues(bot, group_id, bosses, subscribers=False, member_names=True):
    queues = {}
    for boss in bosses:
        order = boss["order"]
        queues[order] = {
            "apply": await ApplyDao(group_id).get_apply(order),
            "subscribe": await SubscribeDao(group_id).get_subscriber(order) if subscribers else [],
            "tree": await TreeDao(group_id).get_tree(order),
        }
    if not member_names:
        return queues, {}
    uids = {entry[0] for queue in queues.values() for entries in queue.values() for entry in entries}
    names = {}
    for uid in uids:
        try:
            member = await bot.get_group_member_info(group_id=group_id, user_id=uid)
            names[uid] = member.get("card") or member.get("nickname") or f"QQ {uid}"
        except Exception:
            names[uid] = f"QQ {uid}"
    return queues, names


@sv.on_prefix('登记会战成员', '取消会战成员登记')
async def member_registration(bot, ev):
    if not getattr(ev, "group_id", None):
        await bot.send(ev, "请在公会群中登记成员身份。")
        return
    mentions = [segment.data.get("qq") for segment in ev.message if segment.type == "at"]
    if len(mentions) > 1 or any(not re.fullmatch(r'[1-9][0-9]{0,19}', str(qq)) for qq in mentions):
        await bot.send(ev, "每次只能为一名成员登记，不能@全体。")
        return
    qq = int(mentions[0]) if mentions else ev.user_id
    if qq != ev.user_id and not priv.check_priv(ev, priv.ADMIN):
        await bot.send(ev, "代他人操作会战成员登记需要群管理员权限。")
        return
    argument = "".join(segment.data.get("text", "") for segment in ev.message if segment.type == "text").strip()
    cancel = ev.prefix == '取消会战成员登记'
    if (cancel and argument) or (not cancel and not re.fullmatch(r'[1-9][0-9]*', argument)):
        await bot.send(ev, "格式：【登记会战成员 游戏ID】或【取消会战成员登记】；群管理员可附加@成员。")
        return
    path = os.path.join(clan_path, str(ev.group_id), "member_links.json")
    async with _member_link_lock:
        links = await load_config(path)
        if not isinstance(links, dict) and os.path.isfile(path):
            await bot.send(ev, "身份登记文件无法读取，请管理员检查；未覆盖已有登记。")
            return
        if cancel:
            if not isinstance(links, dict) or str(qq) not in links:
                await bot.send(ev, "该QQ尚未登记会战成员。")
                return
            links = dict(links)
            links.pop(str(qq))
            message = f"已取消QQ {qq}的会战成员登记。"
        else:
            config = await load_config(os.path.join(clan_path, str(ev.group_id), "clanbattle.json"))
            try:
                links = register_member_link(links, member_roster(config), qq, argument)
            except ValueError as error:
                await bot.send(ev, str(error))
                return
            message = f"已登记QQ {qq} ↔ {member_roster(config)[argument]}（游戏ID {argument}）。\n仅登记身份对应，不需要账号密码。"
        try:
            await write_config(path + ".tmp", links)
            os.replace(path + ".tmp", path)
        except OSError:
            logger.exception("priconne member registration save failed")
            await bot.send(ev, "身份登记保存失败，请重试；原登记已保留。")
            return
    await bot.send(ev, MessageSegment.text(message))


def _dispatch_ready(snapshot, online, now, period):
    synced = snapshot.get("records_synced_at")
    return bool(period and period.active(now) and online and snapshot.get("clan_battle_id") == period.id
                and snapshot.get("record_sync_ok") is True and type(synced) in (int, float)
                and 0 <= now - synced <= 120)


@sv.on_fullmatch('今日出刀', '今日刀表')
async def today_state(bot, ev):
    if not getattr(ev, "group_id", None):
        await bot.send(ev, "请在公会群中查询报表。")
        return
    group_id = ev.group_id
    now = int(time.time())
    config = await load_config(os.path.join(clan_path, str(group_id), "clanbattle.json"))
    period = await _event_period(bot, ev)
    if period is None:
        return
    data = await RecordDao(group_id).get_report_records(
        max(period.start, int(pcr_date(now).timestamp())), min(period.end, now + 1)
    ) if period.active(now) else []
    snapshot, online = await _report_context(group_id, now, period)
    hint = "" if _dispatch_ready(snapshot, online, now, period) else "战绩同步待核验。" if online else "监控离线，记录待核验。"
    await bot.send(ev, daily_report(data, config, now, period, hint))


@sv.on_fullmatch('出刀时段')
async def time_preference(bot, ev):
    if not getattr(ev, "group_id", None):
        await bot.send(ev, "请在公会群中查询报表。")
        return
    group_id = ev.group_id
    now = int(time.time())
    config = await load_config(os.path.join(clan_path, str(group_id), "clanbattle.json"))
    data = await RecordDao(group_id).get_report_records(0, now + 1)
    try:
        period = await get_period()
    except ValueError:
        period = None
    snapshot, online = await _report_context(group_id, now, period)
    bosses = snapshot_bosses(snapshot)
    queues_ready = period and period.active(now) and config and config.get("clan_battle_id") == period.id
    queues, _ = await _report_queues(bot, group_id, bosses, subscribers=True, member_names=False) if queues_ready and bosses else ({}, {})
    links = await load_config(os.path.join(clan_path, str(group_id), "member_links.json"))
    now = int(time.time())
    snapshot, online = await _report_context(group_id, now, period)
    bosses = snapshot_bosses(snapshot)
    dispatch = build_dispatch(data, config, now, period, links, bosses, queues,
                              _dispatch_ready(snapshot, online, now, period))
    await bot.send(ev, report_status(snapshot, online, now) + "\n"
                   + preference_report(data, config, now, activity_report(dispatch, group_id)))


@sv.on_fullmatch('会战指挥台', 'BOSS推进参考', 'boss推进参考')
async def command_center(bot, ev):
    if not getattr(ev, "group_id", None):
        await bot.send(ev, "请在公会群中查询报表。")
        return
    group_id = ev.group_id
    now = int(time.time())
    period = await _event_period(bot, ev)
    if period is None:
        return
    snapshot, online = await _report_context(group_id, now, period)
    header = "会战指挥台\n" + period.label(now) + "\n" + report_status(snapshot, online, now)
    bosses = snapshot_bosses(snapshot)
    records = await RecordDao(group_id).get_report_records(period.start, min(period.end, now + 1))
    config = await load_config(os.path.join(clan_path, str(group_id), "clanbattle.json"))
    links = await load_config(os.path.join(clan_path, str(group_id), "member_links.json"))
    if bosses is None:
        boss_text = snapshot.get("boss")
        if not isinstance(boss_text, str):
            boss_text = "暂无历史进度。"
        await bot.send(ev, MessageSegment.text(
            header + "\n" + boss_text
            + "\n缺少结构化状态，请开启出刀监控刷新；当前队列有效性未知。"
        ))
        dispatch = build_dispatch(records, config, now, period, links)
        if dispatch["active"] and dispatch["members"]:
            await bot.send(ev, coordination_reports(dispatch, group_id))
        return
    queues_ready = period.active(now) and config and config.get("clan_battle_id") == period.id
    queues, names = await _report_queues(bot, group_id, bosses, subscribers=True) if queues_ready else ({}, {})
    now = int(time.time())
    snapshot, online = await _report_context(group_id, now, period)
    latest_bosses = snapshot_bosses(snapshot)
    online = online and latest_bosses is not None
    bosses = latest_bosses or bosses
    header = "会战指挥台\n" + period.label(now) + "\n" + report_status(snapshot, online, now)
    if not queues_ready:
        header += "\n本期登记未就绪或活动已结束，现场队列待确认。"
    dispatch = build_dispatch(records, config, now, period, links, bosses, queues,
                              _dispatch_ready(snapshot, online, now, period))
    table, details = control_report(
        bosses, records, queues, names, now, online, period.id, coordination_reports(dispatch, group_id)
    )
    await bot.send(ev, header + "\n完整刀参考仅使用本期同王同阶段已保存战绩。\n" + table)
    # 登记留言作为纯文本发送，避免被解析成 CQ 图片或 @。
    await bot.send(ev, MessageSegment.text(details))


async def _review_payload(group_id, period, now, final=False):
    snapshot, _ = await _report_context(group_id, now, period)
    synced_at = snapshot.get("records_synced_at", 0)
    sync_ok = False
    clan = clanbattle_info.get(group_id)
    if final and clan is not None and getattr(getattr(clan, "event", None), "id", None) == period.id:
        try:
            sync_ok = await clan.sync_final_records(period) is True
            if sync_ok:
                synced_at = int(time.time())
        except Exception as e:
            logger.opt(exception=e).warning(f"期末战绩补采失败，group={group_id}")
    config = await load_config(os.path.join(clan_path, str(group_id), "clanbattle.json")) or {}
    roster = member_roster(config) if config.get("clan_battle_id") == period.id else {}
    records = await RecordDao(group_id).get_report_records(period.start, min(period.end, now + 1))
    return dict(period_id=period.id, group_id=group_id, now=now, records=records,
                config={"clan_battle_id": period.id, "member_by_id": roster},
                sync_ok=sync_ok, synced_at=synced_at)


@sv.on_fullmatch("会战复盘", "会战总结", "刀伤分布", "刀伤分档")
async def battle_review(bot, ev):
    if not getattr(ev, "group_id", None):
        await bot.send(ev, "请在公会群中查询报表。")
        return
    period = await _event_period(bot, ev)
    if period is None:
        return
    now = int(time.time())
    payload = await _review_payload(ev.group_id, period, now)
    data = build_review(payload["records"], payload["config"], now, period, ev.group_id)
    command = ev.message.extract_plain_text().strip()
    pages = ("distribution",) if command == "刀伤分布" else (("ranges",) if command == "刀伤分档" else REVIEW_PAGES)
    for index, page in enumerate(pages):
        image = await asyncio.to_thread(render_review, data, page)
        await bot.send(ev, (f"第{period.id}期会战复盘｜已保存战绩\n" if index == 0 else "") + image)


async def _send_event_summary(bot, group_id, period, now):
    async def prepare():
        return await _review_payload(group_id, period, now, final=True)

    async def render(payload, page):
        if payload.get("group_id") != group_id:
            raise ValueError("总结发送记录群号不匹配，取消发送。")
        data = build_review(payload["records"], payload["config"], payload["now"], period, group_id)
        image = await asyncio.to_thread(render_review, data, page)
        if page == "overview":
            status = "期末战绩已同步" if payload["sync_ok"] else "期末补采未完成，仅展示已保存战绩"
            return f"第{period.id}期会战总结｜{status}\n" + image
        return image

    async def send(page, message):
        await send_group(bot, group_id, message)

    return await send_summary(os.path.join(clan_path, str(group_id), "summary_send.json"),
                              period, now, prepare, render, send)


@sv.scheduled_job("cron", minute="*/5", timezone=ZoneInfo("Asia/Shanghai"), max_instances=1, coalesce=True)
async def final_summary_broadcast():
    now = int(time.time())
    try:
        period = await get_period(now=now)
    except ValueError:
        return
    if not summary_due(period, now):
        return
    from src.plugins.permission_admin.core import get_permission_manager

    blocked = (get_permission_manager().get_snapshot("priconne") or {}).get("blocked_groups", [])
    for group_id, info in list(run_group.items()):
        profile = info.get("summary") if isinstance(info, dict) else None
        if not profile or profile.get("period_id") != period.id or group_id in blocked:
            continue
        try:
            bot = get_bot(profile["self_id"])
            await _send_event_summary(bot, group_id, period, now)
        except Exception as e:
            logger.opt(exception=e).warning(f"会战总结发送失败，将重试，group={group_id}, period={period.id}")


@sv.on_fullmatch('昨日出刀')
async def yesterday_state(bot, ev):
    group_id = ev.group_id
    period = await _event_period(bot, ev)
    if period is None:
        return
    db = RecordDao(group_id, period)
    data = await db.get_day_rcords(int(time.time()) - 3600 * 24)
    if not data:
        await bot.send(ev, period.label(time.time()) + "\n本期该日无战绩，请核验出刀监控。")
        return
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
    period = await _event_period(bot, ev)
    if period is None:
        return
    db = RecordDao(group_id, period)
    data = await db.get_all_records()
    if not data:
        await bot.send(ev, "数据库为空，请确保开启出刀监控")
        return
    max_dao = await db.get_max_dao()
    players, all_damage, all_score = clanbattle_report(data, max_dao)
    img = await get_cbreport(players, all_damage, all_score)
    pending = sum(row.get("effective_damage") is None for row in data)
    coverage = f"{pending}条实际扣血待核验，排名与占比仅按已核验部分计算。" if pending else "按实际扣血计伤害与分数。"
    await bot.send(ev, period.label(time.time()) + "\n" + coverage + "刀型按默认配对推断。\n" + img)


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
    period = await _event_period(bot, ev)
    if period is None:
        return
    db = RecordDao(group_id, period)
    data = await db.get_player_records(name, day)
    if not data:
        await bot.send(ev, "数据库为空，请确保开启出刀监控或使用正确的角色名")
        return
    img = await get_plyerreport(data)
    await bot.send(ev, period.label(time.time()) + "\n" + img)


@sv.on_prefix('出刀详情')
async def player_report(bot, ev):
    if id := ev.message.extract_plain_text().strip():
        if not id.isdigit():
            await bot.send(ev, "请输入正确的出刀编号")
        else:
            period = await _event_period(bot, ev)
            if period is None:
                return
            detail = RecordDao(ev.group_id, period)
            info = await detail.get_history(id)
            if info:
                await bot.send(ev, await dao_detial(info))
            else:
                await bot.send(ev, "请检查你的出刀编号是否正确。")

@sv.on_rex(r'修正出刀\s?(\d+)\s?(完整刀|尾刀|补偿)?')
async def correct_dao(bot, ev):
    period = await _event_period(bot, ev)
    if period is None:
        return
    records = RecordDao(ev.group_id, period)
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
    period = await _event_period(bot, ev)
    if period is None:
        return
    if not period.active(time.time()):
        await bot.send(ev, period.label(time.time()) + "\n当前不在出刀活动时间内，不催刀。")
        return
    db = RecordDao(group_id, period)
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
    period = await _event_period(bot, ev)
    if period is None:
        return
    db = RecordDao(group_id, period)
    data = await db.get_all_records()
    if not data:
        await bot.send(ev, "数据库为空，请确保开启出刀监控或使用“回归性原理”进行修正")
    else:
        special = await load_config(os.path.join(clan_path, f'{group_id}', "clanbattle.json"))
        special = {} if not special else special["kpi"] if "kpi" in special else {}
        players = kpi_report(data, special)
        img = await get_kpireport(players)
        await bot.send(ev, period.label(time.time()) + "\n" + img)


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
async def cache_run_groups(bot, ev):
    if not await _is_superuser(bot, ev):
        await bot.send(ev, "权限不足")
        return
    saved = await _save_run_group()
    await bot.send(ev, "成功" if saved else "保存失败，请检查日志")

@sv.on_fullmatch("提醒掉线")
async def notify_offline_monitors(bot, ev):
    if not await _is_superuser(bot, ev):
        await bot.send(ev, "权限不足")
        return

    current_bot = get_bot()
    for gid, info in list(run_group.items()):
        if not isinstance(info, dict) or not info.get("qq_id"):
            continue
        clan_info = clanbattle_info.get(gid)
        if clan_info is not None and clan_info.loop_check:
            continue
        _invalidate_monitor_loop(gid)
        try:
            await current_bot.send_group_msg(
                self_id=info.get("self_id"),
                group_id=gid,
                message="遭遇神秘的桥本环奈偷袭，请检查出刀监控",
            )
        except Exception as e:
            logger.opt(exception=e).warning(
                f"priconne offline reminder failed, group={gid}"
            )
        _set_monitor_stopped(gid)
    saved = await _save_run_group()
    await bot.send(ev, "处理完成" if saved else "保存失败，请检查日志")

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
    _restore_run_group(await load_config(run_path))
    for gid, info in list(run_group.items()):
        if not isinstance(info, dict) or not info.get("qq_id"):
            continue  # 旧格式无 qq_id，无法自动登录，跳过
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
            _set_monitor_registered(gid, info.get("self_id"), qq_id)
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
