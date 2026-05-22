from __future__ import annotations

import traceback
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import Any
from nonebot.adapters import Event as BotEvent, Message, Bot
from nonebot.params import CommandArg
from nonebot.permission import SUPERUSER
from nonebot.log import logger

from ...infra.db.models import Event as DbEvent, Team, ensure_user_by_qq, UserAccount, QQ_PLATFORM
from ...domains.score_validator import format_song_key
from ...domains.auto_score_updater import auto_update_event_scores
from ...domains.maimai.services.song_data_sync import load_mai_song_by_id_from_db
from ...shared.bot_response import BotResponse
from ._response import finish_with, send_with


def _group_id_from_event(event: BotEvent) -> str | None:
    raw = getattr(event, "group_id", None)
    if raw is None:
        return None
    return str(raw)


def _is_group_event(event: BotEvent) -> bool:
    return getattr(event, "group_id", None) is not None


async def is_admin(bot: Bot, event: BotEvent) -> bool:
    """检查用户是否为管理员或 SUPERUSER"""
    if await SUPERUSER(bot, event):
        return True

    group_id = _group_id_from_event(event)
    if group_id is not None:
        user_id = event.get_user_id()
        try:
            member_info = await bot.get_group_member_info(group_id=group_id, user_id=int(user_id))
            role = member_info.get("role", "member")
            return role in ["admin", "owner"]
        except Exception as e:
            traceback.print_exc()
            logger.warning(f"获取群成员信息失败: {e}")
            return False

    return False


def is_primary_group(event_obj: DbEvent, group_id: str | None) -> bool:
    """检查是否为主群"""
    if group_id is None:
        return event_obj.group_id is None  # type: ignore
    return event_obj.group_id == group_id  # type: ignore


def can_access_event(event_obj: DbEvent, group_id: str | None) -> bool:
    """检查是否可以访问赛事（主群或次群）"""
    if group_id is None:
        return event_obj.group_id is None  # type: ignore
    # 主群或在额外群组列表中
    return event_obj.group_id == group_id or group_id in (event_obj.extra_group_ids or [])  # type: ignore


def format_team_name(team) -> str:
    """格式化队伍名称，如果有 real_name 则附加在括号中"""
    name = team.name  # type: ignore
    if team.real_name:  # type: ignore
        return f"{name}({team.real_name})"  # type: ignore
    return name


async def get_current_or_prompt_event(event: BotEvent, event_name: str | None = None):
    """获取当前进行中的赛事，如果有多个则返回提示信息（支持次群访问）"""
    # 获取当前群号（如果在群聊中）
    current_group_id = None
    if _is_group_event(event):
        current_group_id = str(event.group_id)
    
    # 如果指定了赛事名，查询并检查访问权限
    if event_name:
        target_event = await DbEvent.get_or_none(name=event_name)
        if not target_event:
            return None, f"赛事 '{event_name}' 不存在"
        # 检查是否可以访问
        if not can_access_event(target_event, current_group_id):
            return None, f"赛事 '{event_name}' 不存在或不属于当前群聊"
        return target_event, None
    
    # 获取当前进行中的赛事（包括主群和次群）
    from ...config import Config
    from nonebot import get_plugin_config
    plugin_config = get_plugin_config(Config)
    tz = ZoneInfo(plugin_config.timezone)
    now = datetime.now(tz)
    
    all_events = await DbEvent.filter(
        start_time__lte=now,
        end_time__gte=now
    ).all()
    
    # 筛选可访问的赛事
    ongoing_events = [e for e in all_events if can_access_event(e, current_group_id)]
    
    if len(ongoing_events) == 0:
        return None, "当前没有进行中的赛事，请指定赛事名称"
    elif len(ongoing_events) == 1:
        return ongoing_events[0], None
    else:
        # 多个进行中的赛事，提示用户选择
        event_list = "\n".join([f"  - {e.name}" for e in ongoing_events])
        return None, f"当前有多个进行中的赛事，请指定赛事名称：\n{event_list}"


async def query_event_rank(event_name: str, event: BotEvent, send_func, finish_func):
    """查询赛事排名的共享逻辑（支持次群访问）"""
    # 获取当前群号
    current_group_id = None
    if _is_group_event(event):
        current_group_id = str(event.group_id)
    
    # 查询赛事
    target_event = await DbEvent.get_or_none(name=event_name)
    
    if not target_event:
        return None  # 赛事不存在
    
    # 检查访问权限
    if not can_access_event(target_event, current_group_id):
        return None  # 没有访问权限

    # 自动更新所有队伍的成绩
    from ...config import Config
    from nonebot import get_plugin_config
    plugin_config = get_plugin_config(Config)
    dev_headers = {'Authorization': plugin_config.lxns_api_key}
    tz = ZoneInfo(plugin_config.timezone)
    
    now = datetime.now(tz)
    try:
        await send_func("正在自动更新成绩...")
        updated_teams, total_members, update_info = await auto_update_event_scores(
            target_event,
            dev_headers
        )

        print(f"自动更新赛事 '{event_name}' 成绩完成: 更新队伍数={updated_teams}, 成员数={total_members}, 详情={update_info}")
        
        if updated_teams > 0:
            await send_func(
                f"成绩更新完成！共更新 {updated_teams} 个队伍，{total_members} 名成员的成绩\n" + 
                f"请自行关注成绩同步是否有误，并及时反馈问题。"
            )
    except Exception as e:
        traceback.print_exc()
        logger.error(f"自动更新成绩失败: {e}")
        await send_func("成绩更新失败，将显示现有排名")

    teams = await Team.filter(event=target_event).prefetch_related("members")
    if not teams:
        await finish_func(f"赛事 '{event_name}' 暂无队伍")
        return None

    # 计算总分并排序（总分 = 所有课题曲的 achievements 总和）
    team_scores = []
    for team in teams:
        total = 0
        total_dx_score = 0
        score_details = []
        
        if team.scores:
            # 按歌曲顺序收集成绩详情
            for key, score_data in team.scores.items():  # type: ignore
                if isinstance(score_data, dict):
                    song_name = score_data.get("song_name", "未知")
                    ach = score_data.get("achievements", 0)
                    dx = score_data.get("dx_score", 0)
                    total += ach
                    total_dx_score += dx
                    score_details.append(f" {song_name}: {ach:.4f}% (DX_Score: {dx})\n")
        
        member_count = len(await team.members.all())  # type: ignore
        display_name = format_team_name(team)
        team_scores.append((display_name, total, total_dx_score, member_count, score_details))

    team_scores.sort(key=lambda x: (x[1], x[2]), reverse=True)

    # 生成排名信息
    lines = [f"赛事 '{event_name}' 排名：\n"]
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    
    for idx, (name, score, total_dx_score, _, details) in enumerate(team_scores, 1):
        # 使用奖牌或数字
        rank_display = medals.get(idx, f"{idx}.")
        
        # 组装成绩详情
        if details:
            details_str = "".join(details)
            lines.append(f"{rank_display} {name} \n{details_str} 总分: {score:.4f}% (DX_Score: {total_dx_score})")
        else:
            lines.append(f"{rank_display} {name} \n 暂无成绩")
        
        # 第8名后添加分隔符
        if idx == 8 and len(team_scores) > 8:
            lines.append("☆>>>>>>>>>>>>>>>>>>>>")

    await finish_func("\n".join(lines))
    return True


def register_event_commands(event_group):
    """注册赛事管理相关命令"""

    help_command = event_group.command("help", force_whitespace=True)

    @help_command.handle()
    async def handle_help(event: BotEvent):
        await help_command.finish(
            "[event] 赛事管理帮助\n"
            + "创建赛事（仅管理员）：/event create <名称> <开始时间> <结束时间>\n"
            + "  时间格式：YYYY-MM-DD HH:MM\n"
            + "设置课题曲（仅管理员）：/event songs <赛事名称> <歌曲JSON>\n"
            + "创建队伍（仅管理员）：/event team create <赛事名称> <队伍ID> <真实名称> [图标图片]\n"
            + "  注：创建队伍时会自动将队长加入队伍（如队长未在该赛事其他队伍中）\n"
            + "加入队伍：/event team join <队伍名称>\n"
            + "退出队伍：/event team leave <队伍名称>\n"
            + "改名队伍（队长/管理员）：/event team rename <旧名称> <新名称>\n"
            + "删除队伍（队长/管理员）：/event team delete <队伍名称>\n"
            + "手动提交成绩（仅管理员）：/event submit <赛事名称> <队伍> <课题曲编号> <分数> <dxscore>\n"
            + "查看队伍：/event team info <队伍名称>\n"
            + "队伍列表：/event team list [赛事名称]\n"
            + "查看排名（自动更新）：/event rank <赛事名称>\n"
            + "列出所有赛事：/event list\n"
            + "\n赛事群组管理（仅管理员）：\n"
            + "绑定次群：/event bind <赛事名称>\n"
            + "解绑次群：/event unbind <赛事名称>\n"
            + "  注：次群仅可查看排名，不能创建队伍、加入队伍等\n"
        )

    # 创建赛事（仅管理员/SUPERUSER）
    create_command = event_group.command("create", force_whitespace=True)

    @create_command.handle()
    async def handle_create_event(bot: Bot, event: BotEvent, args: Message = CommandArg()):
        # 权限检查
        if not await is_admin(bot, event):
            await create_command.finish("只有管理员或 SUPERUSER 才能创建赛事")
        user_id = event.get_user_id()
        text = args.extract_plain_text().strip()

        if not text:
            await create_command.finish(
                "用法：/event create <名称> <开始时间> <结束时间>\n"
                "时间格式：YYYY-MM-DD HH:MM\n"
                "示例：/event create 春季赛 2025-03-01 10:00 2025-03-31 23:59"
            )

        parts = text.split()
        if len(parts) < 5:
            await create_command.finish("参数不足，需要：<名称> <开始日期> <开始时间> <结束日期> <结束时间>")

        name = parts[0]
        start_str = f"{parts[1]} {parts[2]}"
        end_str = f"{parts[3]} {parts[4]}"

        # 获取配置的时区
        from ...config import Config
        from nonebot import get_plugin_config
        plugin_config = get_plugin_config(Config)
        tz = ZoneInfo(plugin_config.timezone)
        
        try:
            # 解析为本地时区的时间
            start_time = datetime.strptime(start_str, "%Y-%m-%d %H:%M").replace(tzinfo=tz)
            end_time = datetime.strptime(end_str, "%Y-%m-%d %H:%M").replace(tzinfo=tz)
        except ValueError:
            traceback.print_exc()
            await create_command.finish("时间格式错误，请使用：YYYY-MM-DD HH:MM")
            return

        if start_time >= end_time:
            await create_command.finish("开始时间必须早于结束时间")

        # 检查赛事是否已存在
        existing = await DbEvent.get_or_none(name=name)
        if existing:
            await create_command.finish(f"赛事 '{name}' 已存在")

        # 获取群号（如果在群聊中）
        group_id = None
        if _is_group_event(event):
            group_id = str(event.group_id)

        # 创建赛事
        user = await ensure_user_by_qq(user_id)
        new_event = await DbEvent.create(
            name=name,
            group_id=group_id,
            start_time=start_time,
            end_time=end_time,
            created_by=user,
        )

        # 转换到本地时区显示
        start_local = new_event.start_time.astimezone(tz)
        end_local = new_event.end_time.astimezone(tz)
        
        group_info = f"\n绑定群聊：{group_id}" if group_id else ""
        await create_command.finish(
            f"赛事创建成功！\n"
            f"名称：{new_event.name}\n"
            f"开始时间：{start_local.strftime('%Y-%m-%d %H:%M')}\n"
            f"结束时间：{end_local.strftime('%Y-%m-%d %H:%M')}"
            + group_info
        )

    # 列出所有赛事
    list_command = event_group.command("list", force_whitespace=True)

    @list_command.handle()
    async def handle_list_events(event: BotEvent):
        # 获取当前群号（如果在群聊中）
        group_id = None
        if _is_group_event(event):
            group_id = str(event.group_id)
        
        # 只显示当前群聊的赛事
        if group_id:
            events = await DbEvent.filter(group_id=group_id).order_by("-created_at")
        else:
            events = await DbEvent.all().order_by("-created_at")
        
        if not events:
            await list_command.finish("暂无赛事")

        # 获取配置的时区
        from ...config import Config
        from nonebot import get_plugin_config
        plugin_config = get_plugin_config(Config)
        tz = ZoneInfo(plugin_config.timezone)
        
        lines = ["当前赛事列表："]
        now = datetime.now(tz)
        for evt in events:
            # 转换到本地时区显示
            start_local = evt.start_time.astimezone(tz)
            end_local = evt.end_time.astimezone(tz)
            status = "进行中" if evt.start_time <= now <= evt.end_time else "未开始" if now < evt.start_time else "已结束"
            lines.append(
                f"\n[{evt.name}] {status}\n"
                f"  时间：{start_local.strftime('%Y-%m-%d %H:%M')} ~ {end_local.strftime('%Y-%m-%d %H:%M')}"
            )

        await list_command.finish("\n".join(lines))

    # 绑定次群（仅管理员/SUPERUSER）
    bind_command = event_group.command("bind", force_whitespace=True)

    @bind_command.handle()
    async def handle_bind_group(bot: Bot, event: BotEvent, args: Message = CommandArg()):
        # 权限检查
        if not await is_admin(bot, event):
            await bind_command.finish("只有管理员或 SUPERUSER 才能绑定次群")
        
        # 必须在群聊中使用
        if not _is_group_event(event):
            await bind_command.finish("该命令只能在群聊中使用")
        
        current_group_id = str(event.group_id)
        event_name = args.extract_plain_text().strip()

        if not event_name:
            await bind_command.finish("用法：/event bind <赛事名称>")

        # 查找赛事
        target_event = await DbEvent.get_or_none(name=event_name)
        if not target_event:
            await bind_command.finish(f"赛事 '{event_name}' 不存在")

        # 检查是否已经是主群
        if target_event.group_id == current_group_id:  # type: ignore
            await bind_command.finish(f"当前群已是赛事 '{event_name}' 的主群")

        # 检查是否已经在次群列表中
        extra_groups = target_event.extra_group_ids or []  # type: ignore
        if current_group_id in extra_groups:
            await bind_command.finish(f"当前群已绑定赛事 '{event_name}'")

        # 添加到次群列表
        extra_groups.append(current_group_id)
        target_event.extra_group_ids = extra_groups  # type: ignore
        await target_event.save()  # type: ignore

        await bind_command.finish(
            f"绑定成功！\n"
            f"当前群已绑定赛事 '{event_name}' 为次群\n"
            f"注：次群仅可查看排行榜，不能创建队伍、加入队伍等"
        )

    # 解绑次群（仅管理员/SUPERUSER）
    unbind_command = event_group.command("unbind", force_whitespace=True)

    @unbind_command.handle()
    async def handle_unbind_group(bot: Bot, event: BotEvent, args: Message = CommandArg()):
        # 权限检查
        if not await is_admin(bot, event):
            await unbind_command.finish("只有管理员或 SUPERUSER 才能解绑次群")
        
        # 必须在群聊中使用
        if not _is_group_event(event):
            await unbind_command.finish("该命令只能在群聊中使用")
        
        current_group_id = str(event.group_id)
        event_name = args.extract_plain_text().strip()

        if not event_name:
            await unbind_command.finish("用法：/event unbind <赛事名称>")

        # 查找赛事
        target_event = await DbEvent.get_or_none(name=event_name)
        if not target_event:
            await unbind_command.finish(f"赛事 '{event_name}' 不存在")

        # 检查是否是主群
        if target_event.group_id == current_group_id:  # type: ignore
            await unbind_command.finish("主群不能解绑，如需解绑请删除赛事")

        # 检查是否在次群列表中
        extra_groups = target_event.extra_group_ids or []  # type: ignore
        if current_group_id not in extra_groups:
            await unbind_command.finish(f"当前群未绑定赛事 '{event_name}'")

        # 从次群列表中移除
        extra_groups.remove(current_group_id)
        target_event.extra_group_ids = extra_groups  # type: ignore
        await target_event.save()  # type: ignore

        await unbind_command.finish(f"解绑成功！当前群已解绑赛事 '{event_name}'")

    # 创建队伍（仅管理员/SUPERUSER）
    team_create_command = event_group.command("team.create", aliases={"team create"}, force_whitespace=True)

    @team_create_command.handle()
    async def handle_create_team(bot: Bot, event: BotEvent, args: Message = CommandArg()):
        # 权限检查
        if not await is_admin(bot, event):
            await team_create_command.finish("只有管理员或 SUPERUSER 才能创建队伍")
        user_id = event.get_user_id()
        text = args.extract_plain_text().strip()

        if not text:
            await team_create_command.finish(
                "用法：/event team create <赛事名称> <队伍ID> <真实名称> [图标图片]\n"
                "示例：/event team create XIC1st xju 新疆大学 [图片]\n"
                "提示：可以在命令后面附带图片作为队伍图标"
            )

        parts = text.split(maxsplit=4)
        if len(parts) < 2:
            await team_create_command.finish("参数不足，需要：<赛事名称> <队伍ID> [真实名称] [图标图片]")

        event_name = parts[0]
        team_name = parts[1]
        real_name = parts[2] if len(parts) > 2 else None
        
        # 从消息中提取图片 URL 并下载转换为 base64
        icon_data = None
        for seg in args:
            if seg.type == "image":
                # 优先使用 url 字段，如果没有则使用 file 字段
                icon_url = seg.data.get("url") or seg.data.get("file")
                if icon_url:
                    try:
                        # 使用 HttpClient 下载图片
                        from ...infra.http import http_client
                        import base64
                        icon_bytes = await http_client.get_bytes(icon_url)
                        # 转换为 base64
                        icon_data = base64.b64encode(icon_bytes).decode('utf-8')
                    except Exception as e:
                        traceback.print_exc()
                        logger.warning(f"下载队伍图标失败: {e}")
                break

        # 检查赛事是否存在并验证主群权限
        current_group_id = None
        if _is_group_event(event):
            current_group_id = str(event.group_id)
        
        target_event = await DbEvent.get_or_none(name=event_name)
        
        if not target_event:
            await team_create_command.finish(f"赛事 '{event_name}' 不存在")
        
        # 检查是否为主群（创建队伍需要主群权限）
        if not is_primary_group(target_event, current_group_id):
            await team_create_command.finish("只有赛事主群才能创建队伍")

        # 检查队伍是否已存在
        existing_team = await Team.get_or_none(name=team_name)
        if existing_team:
            await team_create_command.finish(f"队伍 '{team_name}' 已存在")

        # 创建队伍
        user = await ensure_user_by_qq(user_id)
        new_team = await Team.create(
            name=team_name,
            real_name=real_name,
            icon=icon_data,
            event=target_event,
            created_by=user,
        )

        # 检查创建者是否已在该赛事的其他队伍中
        existing_teams = await Team.filter(event=target_event).prefetch_related("members")
        is_already_in_other_team = False
        for team in existing_teams:
            if team.id != new_team.id:  # type: ignore
                members = await team.members.all()  # type: ignore
                if user in members:
                    is_already_in_other_team = True
                    break
        
        # 如果创建者未在该赛事的其他队伍中，自动将其加入队伍
        captain_info = ""
        if not is_already_in_other_team:
            await new_team.members.add(user)  # type: ignore
            captain_info = f"\n您 已自动加入队伍"
        else:
            captain_info = "\n注：队长已在该赛事的其他队伍中，未自动加入"

        icon_info = "\n已设置队伍图标" if icon_data else ""
        display_name = format_team_name(new_team)
        await team_create_command.finish(
            f"队伍创建成功！\n"
            f"队伍：{display_name}\n"
            f"所属赛事：{target_event.name}" # type: ignore
            + icon_info
            + captain_info
        )

    # 加入队伍
    team_join_command = event_group.command("team.join", aliases={"team join"}, force_whitespace=True)

    @team_join_command.handle()
    async def handle_join_team(event: BotEvent, args: Message = CommandArg()):
        user_id = event.get_user_id()
        team_name = args.extract_plain_text().strip()

        if not team_name:
            await team_join_command.finish("用法：/event team join <队伍名称>")

        # 检查队伍是否存在
        current_group_id = None
        if _is_group_event(event):
            current_group_id = str(event.group_id)
        
        team = await Team.filter(name=team_name).prefetch_related("members", "event").first()
        
        if not team:
            await team_join_command.finish(f"队伍 '{team_name}' 不存在")
        
        # 检查是否为主群（加入队伍需要主群权限）
        target_event = team.event  # type: ignore
        if not is_primary_group(target_event, current_group_id):
            await team_join_command.finish("只有赛事主群才能加入队伍")

        # 确保用户存在
        user = await ensure_user_by_qq(user_id)

        # 检查是否已经是成员
        members = await team.members.all()  # type: ignore
        if user in members:
            await team_join_command.finish(f"你已经是 '{team_name}' 的成员了")

        # 检查是否已在该赛事的其他队伍中
        all_event_teams = await Team.filter(event=target_event).prefetch_related("members")
        for other_team in all_event_teams:
            if other_team.id != team.id:  # type: ignore
                other_members = await other_team.members.all()  # type: ignore
                if user in other_members:
                    await team_join_command.finish(
                        f"你已经在赛事 '{target_event.name}' 的队伍 '{other_team.name}' 中了！\n" # type: ignore
                        f"一个玩家不能同时加入一个赛事的多个队伍\n"
                        f"如需加入新队伍，请先使用 /event team leave {other_team.name} 退出当前队伍" # type: ignore
                    )

        # 加入队伍
        await team.members.add(user)  # type: ignore
        await finish_with(BotResponse(
            text=f" 成功加入队伍 '{team_name}'！",
            reply_to=event.message_id,
        ))

    # 退出队伍
    team_leave_command = event_group.command("team.leave", aliases={"team leave"}, force_whitespace=True)

    @team_leave_command.handle()
    async def handle_leave_team(event: BotEvent, args: Message = CommandArg()):
        user_id = event.get_user_id()
        team_name = args.extract_plain_text().strip()

        if not team_name:
            await team_leave_command.finish("用法：/event team leave <队伍名称>")

        # 检查队伍是否存在
        current_group_id = None
        if _is_group_event(event):
            current_group_id = str(event.group_id)
        
        team = await Team.filter(name=team_name).prefetch_related("members", "event").first()
        
        if not team:
            await team_leave_command.finish(f"队伍 '{team_name}' 不存在")
        
        # 检查是否为主群（退出队伍需要主群权限）
        target_event = team.event  # type: ignore
        if not is_primary_group(target_event, current_group_id):
            await team_leave_command.finish("只有赛事主群才能退出队伍")

        # 确保用户存在
        user = await ensure_user_by_qq(user_id)

        # 检查是否是成员
        members = await team.members.all()  # type: ignore
        if user not in members:
            await team_leave_command.finish(f"你不是 '{team_name}' 的成员")

        # 退出队伍
        await team.members.remove(user)  # type: ignore
        await finish_with(BotResponse(
            text=f" 已退出队伍 '{team_name}'",
            reply_to=event.message_id,
        ))

    # 改名队伍（队长/管理员）
    team_rename_command = event_group.command("team.rename", aliases={"team rename"}, force_whitespace=True)

    @team_rename_command.handle()
    async def handle_rename_team(bot: Bot, event: BotEvent, args: Message = CommandArg()):
        user_id = event.get_user_id()
        text = args.extract_plain_text().strip()

        if not text:
            await team_rename_command.finish("用法：/event team rename <旧名称> <新名称>")

        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            await team_rename_command.finish("参数不足，需要：<旧名称> <新名称>")

        old_name = parts[0]
        new_name = parts[1]

        # 检查旧队伍是否存在
        current_group_id = None
        if _is_group_event(event):
            current_group_id = str(event.group_id)
        
        team = await Team.filter(name=old_name).prefetch_related("created_by", "event").first()
        
        if not team:
            await team_rename_command.finish(f"队伍 '{old_name}' 不存在")
        
        # 检查是否为主群（改名队伍需要主群权限）
        target_event = team.event  # type: ignore
        if not is_primary_group(target_event, current_group_id):
            await team_rename_command.finish("只有赛事主群才能修改队伍名称")

        # 确保用户存在
        user = await ensure_user_by_qq(user_id)

        # 权限检查：只有队长（创建者）或管理员可以改名
        is_captain = team.created_by.id == user.id  # type: ignore
        is_group_admin = await is_admin(bot, event)
        
        if not (is_captain or is_group_admin):
            await team_rename_command.finish("只有队长或管理员才能修改队伍名称")

        # 检查新名称是否已被占用
        existing_team = await Team.filter(name=new_name).first()
        
        if existing_team:
            await team_rename_command.finish(f"队伍名称 '{new_name}' 已被占用")

        # 修改队伍名称
        team.name = new_name  # type: ignore
        await team.save()  # type: ignore
        
        await team_rename_command.finish(
            f"队伍改名成功！\n"
            f"旧名称：{old_name}\n"
            f"新名称：{new_name}"
        )

    # 删除队伍（队长/管理员）
    team_delete_command = event_group.command("team.delete", aliases={"team delete"}, force_whitespace=True)

    @team_delete_command.handle()
    async def handle_delete_team(bot: Bot, event: BotEvent, args: Message = CommandArg()):
        user_id = event.get_user_id()
        team_name = args.extract_plain_text().strip()

        if not team_name:
            await team_delete_command.finish("用法：/event team delete <队伍名称>")

        # 检查队伍是否存在
        current_group_id = None
        if _is_group_event(event):
            current_group_id = str(event.group_id)
        
        team = await Team.filter(name=team_name).prefetch_related("created_by", "event", "members").first()
        
        if not team:
            await team_delete_command.finish(f"队伍 '{team_name}' 不存在")
        
        # 检查是否为主群（删除队伍需要主群权限）
        target_event = team.event  # type: ignore
        if not is_primary_group(target_event, current_group_id):
            await team_delete_command.finish("只有赛事主群才能删除队伍")

        # 确保用户存在
        user = await ensure_user_by_qq(user_id)

        # 权限检查：只有队长（创建者）或管理员可以删除
        is_captain = team.created_by.id == user.id  # type: ignore
        is_group_admin = await is_admin(bot, event)
        
        if not (is_captain or is_group_admin):
            await team_delete_command.finish("只有队长或管理员才能删除队伍")

        # 获取成员数量用于显示
        members = await team.members.all()  # type: ignore
        member_count = len(members)
        event_name = target_event.name  # type: ignore

        # 删除队伍
        await team.delete()  # type: ignore
        
        await team_delete_command.finish(
            f"队伍删除成功！\n"
            f"队伍名称：{team_name}\n"
            f"所属赛事：{event_name}\n"
            f"原成员数：{member_count}"
        )

    # 队伍列表
    team_list_command = event_group.command("team.list", aliases={"team list"}, force_whitespace=True)

    @team_list_command.handle()
    async def handle_team_list(event: BotEvent, args: Message = CommandArg()):
        event_name = args.extract_plain_text().strip() or None
        
        # 获取当前赛事或提示信息
        target_event, error_msg = await get_current_or_prompt_event(event, event_name)
        
        if error_msg:
            await team_list_command.finish(error_msg)
            return
        
        if not target_event:
            await team_list_command.finish(f"赛事 '{event_name}' 不存在")
            return

        # 获取该赛事的所有队伍
        teams = await Team.filter(event=target_event).prefetch_related("members")
        
        if not teams:
            await team_list_command.finish(f"赛事 '{target_event.name}' 暂无队伍")  # type: ignore
            return

        # 计算每个队伍的信息
        team_infos = []
        for team in teams:
            member_count = len(await team.members.all())  # type: ignore
            total_score = 0
            
            if team.scores:  # type: ignore
                for key, score_data in team.scores.items():  # type: ignore
                    if isinstance(score_data, dict):
                        total_score += score_data.get("achievements", 0)
            
            display_name = format_team_name(team)
            team_infos.append((display_name, member_count, total_score))
        
        # 按总分排序
        team_infos.sort(key=lambda x: x[2], reverse=True)
        
        # 生成列表信息
        lines = [f"赛事 '{target_event.name}' 队伍列表（共 {len(teams)} 支队伍）:\n"]  # type: ignore
        
        for name, members, score in team_infos:
            if score > 0:
                lines.append(f"• {name}\n  成员：{members}人 | 总分：{score:.2f}%")
            else:
                lines.append(f"• {name}\n  成员：{members}人 | 暂无成绩")
        
        await team_list_command.finish("\n".join(lines))

    # 查看队伍信息
    team_info_command = event_group.command("team.info", aliases={"team info"}, force_whitespace=True)

    @team_info_command.handle()
    async def handle_team_info(event: BotEvent, args: Message = CommandArg()):
        team_name = args.extract_plain_text().strip()

        if not team_name:
            await team_info_command.finish("用法：/event team info <队伍名称>")

        # 检查队伍是否存在
        current_group_id = None
        if _is_group_event(event):
            current_group_id = str(event.group_id)
        
        team = await Team.filter(name=team_name).prefetch_related("members", "event").first()
        
        if not team:
            await team_info_command.finish(f"队伍 '{team_name}' 不存在")
        
        # 检查访问权限（查看队伍信息支持次群访问）
        target_event = team.event  # type: ignore
        if not can_access_event(target_event, current_group_id):
            await team_info_command.finish(f"该队伍不属于当前群聊")

        members = await team.members.all()  # type: ignore
        member_count = len(members)

        display_name = format_team_name(team)
        info_lines = [
            f"队伍：{display_name}",
            f"所属赛事：{team.event.name}",  # type: ignore
            f"成员数：{member_count}",
        ]
        
        # 显示成员列表
        if members:
            info_lines.append("\n成员列表：")
            for i, member in enumerate(members, 1):
                # 获取该用户的 QQ 账号
                qq_account = await UserAccount.get_or_none(user=member, platform=QQ_PLATFORM)  # type: ignore
                if qq_account:
                    info_lines.append(f"  {i}. {qq_account.account_key}")  # type: ignore
                else:
                    info_lines.append(f"  {i}. 用户#{member.id}")  # type: ignore

        # 如果有图标，发送图片
        icon_bytes = None
        if team.icon:  # type: ignore
            try:
                import base64
                icon_bytes = base64.b64decode(team.icon)  # type: ignore
            except Exception as e:
                traceback.print_exc()
                logger.warning(f"解码队伍图标失败: {e}")

        # 显示每首课题曲的成绩
        if team.scores:  # type: ignore
            info_lines.append("\n课题曲成绩：")
            total_score = 0
            for key, score_data in team.scores.items():  # type: ignore
                if isinstance(score_data, dict):
                    song_name = score_data.get("song_name", "未知")
                    ach = score_data.get("achievements", 0)
                    dx = score_data.get("dx_score", 0)
                    total_score += ach
                    info_lines.append(f"  {song_name}: {ach:.4f}% (DX: {dx})")
            
            # 最后显示总分
            info_lines.append(f"\n总分：{total_score:.2f}%")
        else:
            info_lines.append("\n暂无成绩")

        # 发送消息（如果有图标则先发图标，再发文字信息）
        if icon_bytes is not None:
            await send_with(BotResponse(image=icon_bytes))
        await finish_with(BotResponse(text="\n".join(info_lines)))

    # 查看排名（自动更新成绩）
    rank_command = event_group.command("rank", force_whitespace=True)

    @rank_command.handle()
    async def handle_rank(event: BotEvent, args: Message = CommandArg()):
        event_name = args.extract_plain_text().strip() or None
        
        # 获取当前赛事或提示信息
        target_event, error_msg = await get_current_or_prompt_event(event, event_name)
        
        if error_msg:
            await rank_command.finish(error_msg)
            return
        
        if not target_event:
            await rank_command.finish(f"赛事 '{event_name}' 不存在")
            return

        result = await query_event_rank(
            target_event.name,  # type: ignore
            event,
            rank_command.send,
            rank_command.finish
        )
        
        if result is None:
            await rank_command.finish(f"赛事 '{target_event.name}' 不存在")  # type: ignore

    # 设置课题曲（仅管理员/SUPERUSER）
    songs_command = event_group.command("songs", force_whitespace=True)

    @songs_command.handle()
    async def handle_set_songs(bot: Bot, event: BotEvent, args: Message = CommandArg()):
        # 权限检查
        if not await is_admin(bot, event):
            await songs_command.finish("只有管理员或 SUPERUSER 才能设置课题曲")

        text = args.extract_plain_text().strip()
        if not text:
            await songs_command.finish(
                "用法：/event songs <赛事名称> <歌曲JSON>\n"
                "示例：/event songs 春季赛 [{\"id\":689,\"song_name\":\"Credits\",\"level\":\"13\",\"level_index\":2,\"type\":\"standard\"}]"
            )

        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            await songs_command.finish("参数不足，需要：<赛事名称> <歌曲JSON>")

        event_name = parts[0]
        songs_json = parts[1]

        # 检查赛事是否存在
        current_group_id = None
        if _is_group_event(event):
            current_group_id = str(event.group_id)
        
        target_event = await DbEvent.get_or_none(name=event_name)
        
        if not target_event:
            await songs_command.finish(f"赛事 '{event_name}' 不存在")
        
        # 检查是否为主群（设置课题曲需要主群权限）
        if not is_primary_group(target_event, current_group_id):
            await songs_command.finish("只有赛事主群才能设置课题曲")

        # 解析 JSON
        import json
        try:
            songs = json.loads(songs_json)
            if not isinstance(songs, list):
                await songs_command.finish("课题曲必须是一个数组")
                return
            
            # 验证每首歌的字段
            required_fields = ["id", "song_name", "level", "level_index", "type"]
            for song in songs:
                for field in required_fields:
                    if field not in song:
                        await songs_command.finish(f"课题曲缺少必需字段：{field}")
                        return
        except Exception as e:
            traceback.print_exc()
            await songs_command.finish(f"JSON 解析失败：{str(e)}")
            return

        # 更新课题曲
        target_event.songs = songs  # type: ignore
        await target_event.save() # type: ignore

        song_list = "\n".join([
            f"  {i+1}. {s['song_name']} [{s['type'].upper()}] Lv.{s['level']}"
            for i, s in enumerate(songs)
        ])

        await songs_command.finish(
            f"赛事 '{event_name}' 的课题曲已更新：\n{song_list}"
        )

    # 手动提交成绩（仅管理员/SUPERUSER）
    submit_command = event_group.command("submit", force_whitespace=True)

    @submit_command.handle()
    async def handle_submit_score(bot: Bot, event: BotEvent, args: Message = CommandArg()):
        # 权限检查
        if not await is_admin(bot, event):
            await submit_command.finish("只有管理员或 SUPERUSER 才能手动提交成绩")

        text = args.extract_plain_text().strip()
        if not text:
            await submit_command.finish(
                "用法：/event submit <赛事名称> <队伍名称> <课题曲编号> <分数> <dxscore>\n"
                "示例：/event submit 春季赛 队伍 1 99.5678 850"
            )

        parts = text.split()
        if len(parts) < 5:
            await submit_command.finish("参数不足，需要：<赛事名称> <队伍名称> <课题曲编号> <分数> <dxscore>")

        event_name = parts[0]
        team_name = parts[1]
        
        try:
            song_index = int(parts[2]) - 1  # 转换为 0-based 索引
            achievements = float(parts[3])
            dx_score = int(parts[4])
        except ValueError:
            traceback.print_exc()
            await submit_command.finish("参数格式错误：课题曲编号必须是整数，分数必须是数字，dxscore必须是整数")
            return
        
        if achievements < 0.0 or achievements > 101.0:
            await submit_command.finish("分数必须在 0.0 到 101.0 之间")

        if dx_score < 0:
            await submit_command.finish("dxscore 必须是非负整数")

        # 检查赛事是否存在
        current_group_id = None
        if _is_group_event(event):
            current_group_id = str(event.group_id)
        
        target_event = await DbEvent.get_or_none(name=event_name)
        
        if not target_event:
            await submit_command.finish(f"赛事 '{event_name}' 不存在")
        
        # 检查是否为主群（提交成绩需要主群权限）
        if not is_primary_group(target_event, current_group_id):
            await submit_command.finish("只有赛事主群才能提交成绩")

        # 检查队伍是否存在且属于该赛事
        team = await Team.filter(name=team_name, event=target_event).prefetch_related("event").first()
        
        if not team:
            await submit_command.finish(f"队伍 '{team_name}' 不存在或不属于赛事 '{event_name}'")

        # 获取赛事课题曲
        if not target_event.songs:  # type: ignore
            await submit_command.finish(f"赛事 '{target_event.name}' 还没有设置课题曲")  # type: ignore

        songs: list[dict[str, Any]] = target_event.songs  # type: ignore
        
        # 验证课题曲编号
        if song_index < 0 or song_index >= len(songs):
            await submit_command.finish(f"课题曲编号无效，应在 1-{len(songs)} 之间")

        target_song = songs[song_index]
        song_key = format_song_key(target_song)

        song_info = await load_mai_song_by_id_from_db(target_song['id'])
        if song_info is None:
            await submit_command.finish(f"未找到课题曲数据：{target_song.get('song_name')}")
        if target_song['type'] == 'standard':
            song_current_data = song_info.difficulties.get('standard', [])[target_song['level_index']] # type: ignore
        else:
            song_current_data = song_info.difficulties.get('dx', [])[target_song['level_index']] # type: ignore
        total_dx_score = song_current_data.get('notes').get('total') * 3

        if dx_score > total_dx_score:
            await submit_command.finish(f"dxscore 超过该课题曲的最大值 {total_dx_score}")

        # 更新成绩
        current_scores = team.scores if team.scores else {}  # type: ignore
        old_record = current_scores.get(song_key)  # type: ignore
        
        # 判断是否需要更新
        should_update = False
        if old_record is None:
            should_update = True
        else:
            old_ach = old_record.get("achievements", 0)
            old_dx = old_record.get("dx_score", 0)
            
            if achievements > old_ach:
                should_update = True
            elif achievements == old_ach and dx_score > old_dx:
                should_update = True

        if not should_update:
            await submit_command.finish(
                f"新成绩未超过旧记录\n"
                f"旧记录：{old_record.get('achievements', 0):.4f}% (DX: {old_record.get('dx_score', 0)})\n" # type: ignore
                f"新成绩：{achievements:.4f}% (DX: {dx_score})"
            )

        # 保存新成绩
        current_scores[song_key] = {  # type: ignore
            "achievements": achievements,
            "dx_score": dx_score,
            "song_name": target_song.get("song_name"),
            "level": target_song.get("level"),
            "level_index": target_song.get("level_index"),
            "type": target_song.get("type"),
            "play_time": datetime.now().isoformat(),
        }

        team.scores = current_scores  # type: ignore
        await team.save() # type: ignore

        song_name = target_song.get("song_name", "未知")
        if old_record:
            await submit_command.finish(
                f"成绩更新成功！\n"
                f"队伍：{team_name}\n"
                f"课题曲：{song_name}\n"
                f"旧记录：{old_record.get('achievements', 0):.4f}% (DX: {old_record.get('dx_score', 0)})\n"
                f"新记录：{achievements:.4f}% (DX: {dx_score})"
            )
        else:
            await submit_command.finish(
                f"成绩提交成功！\n"
                f"队伍：{team_name}\n"
                f"课题曲：{song_name}\n"
                f"成绩：{achievements:.4f}% (DX: {dx_score})"
            )


def register_event_rank_matcher():
    """注册赛事排名的自然语言匹配器"""
    from nonebot import on_regex
    from nonebot.params import RegexGroup

    # 匹配 <赛事名>排行榜、<赛事名>排名、<赛事名>榜单、<赛事名>榜
    rank_matcher = on_regex(r"^(.+?)(排行榜|排行|排名|榜单|榜)$", priority=5, block=True)
    
    @rank_matcher.handle()
    async def handle_natural_rank(event: BotEvent, matched: tuple = RegexGroup()):
        if not matched or len(matched) < 2:
            return
        
        event_name = matched[0].strip()
        
        if not event_name:
            return
        
        # 获取当前赛事或提示信息
        target_event, error_msg = await get_current_or_prompt_event(event, event_name)
        
        if error_msg:
            # 如果是找不到赛事，不处理（避免误触发）
            return
        
        if not target_event:
            return
        
        # 检查是否为主群（自然语言匹配只在主群生效）
        current_group_id = None
        if _is_group_event(event):
            current_group_id = str(event.group_id)
        if not is_primary_group(target_event, current_group_id):
            return
        
        # 调用共享的查询函数
        result = await query_event_rank(
            target_event.name,  # type: ignore
            event,
            rank_matcher.send,
            rank_matcher.finish
        )
        
        # 如果返回 None 表示赛事不存在，不处理（避免误触发）
        if result is None:
            return
    
    # 匹配不带赛事名的排行榜查询（如 "排行榜"、"排名"、"榜单"、"榜"）
    simple_rank_matcher = on_regex(r"^(排行榜|排行|排名|榜单|榜)$", priority=5, block=True)
    
    @simple_rank_matcher.handle()
    async def handle_simple_rank(event: BotEvent):
        # 获取当前赛事或提示信息
        target_event, error_msg = await get_current_or_prompt_event(event, None)
        
        if error_msg:
            return  # 静默失败，不显示错误信息
        
        if not target_event:
            return  # 静默失败
        
        # 检查是否为主群（自然语言匹配只在主群生效）
        current_group_id = None
        if _is_group_event(event):
            current_group_id = str(event.group_id)
        if not is_primary_group(target_event, current_group_id):
            return
        
        # 调用共享的查询函数
        await query_event_rank(
            target_event.name,  # type: ignore
            event,
            simple_rank_matcher.send,
            simple_rank_matcher.finish
        )
