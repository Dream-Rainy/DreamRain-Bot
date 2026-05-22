"""自动更新赛事成绩的服务"""
from __future__ import annotations

import traceback
from datetime import datetime, timezone
from typing import Any
from nonebot.log import logger

from ..infra.db.models import Event, Team, User, UserAccount, QQ_PLATFORM
from ..infra.http import http_client
from .score_validator import match_and_validate_records, update_team_scores


def filter_records_by_event_time(
    records: list[dict[str, Any]],
    event_start: datetime,
    event_end: datetime
) -> list[dict[str, Any]]:
    """
    过滤在赛事时间范围内的记录
    
    Args:
        records: 游玩记录列表
        event_start: 赛事开始时间
        event_end: 赛事结束时间
    
    Returns:
        在赛事时间范围内的记录列表
    """
    filtered = []
    for record in records:
        play_time_str = record.get("play_time")
        if not play_time_str:
            continue
        
        try:
            # 解析 ISO 8601 格式时间（如 "2025-11-29T09:34:00Z"）
            play_time = datetime.fromisoformat(play_time_str.replace("Z", "+00:00"))
            
            # 确保 event_start 和 event_end 也是带时区的
            # 如果是 naive datetime，假设为 UTC
            if event_start.tzinfo is None:
                event_start = event_start.replace(tzinfo=timezone.utc)
            if event_end.tzinfo is None:
                event_end = event_end.replace(tzinfo=timezone.utc)
            
            # 统一转换到 UTC 进行比较
            play_time_utc = play_time.astimezone(timezone.utc) if play_time.tzinfo else play_time.replace(tzinfo=timezone.utc)
            event_start_utc = event_start.astimezone(timezone.utc)
            event_end_utc = event_end.astimezone(timezone.utc)
            
            if event_start_utc <= play_time_utc <= event_end_utc:
                filtered.append(record)
        except Exception as e:
            traceback.print_exc()
            logger.warning(f"解析游玩时间失败: {play_time_str}, 错误: {e}")
            continue
    
    return filtered


async def get_friend_code_by_qq(qq: str, dev_headers: dict[str, str]) -> str | None:
    """通过 QQ 号获取 friend_code"""
    try:
        maimai_uri = f"https://maimai.lxns.net/api/v0/maimai/player/qq/{qq}"
        response = await http_client.get_json(maimai_uri, headers=dev_headers)
        
        if response.get("success"):
            return response["data"]["friend_code"]
        return None
    except Exception as e:
        traceback.print_exc()
        logger.error(f"获取 friend_code 失败 (QQ: {qq}): {e}")
        return None


async def get_recent_records(friend_code: str, dev_headers: dict[str, str]) -> list[dict[str, Any]]:
    """获取玩家的最近游玩记录"""
    try:
        recents_uri = f"https://maimai.lxns.net/api/v0/maimai/player/{friend_code}/recents"
        response = await http_client.get_json(recents_uri, headers=dev_headers)
        
        if response.get("success"):
            return response["data"]
        return []
    except Exception as e:
        traceback.print_exc()
        logger.error(f"获取游玩记录失败 (friend_code: {friend_code}): {e}")
        return []


async def auto_update_team_scores(
    team: Team,
    target_songs: list[dict[str, Any]],
    dev_headers: dict[str, str],
    event_start: datetime,
    event_end: datetime
) -> tuple[bool, int, list[str]]:
    """
    自动更新队伍成绩
    
    Args:
        team: 队伍对象
        target_songs: 课题曲列表
        dev_headers: API 请求头
        event_start: 赛事开始时间
        event_end: 赛事结束时间
    
    Returns:
        (是否有更新, 成功更新的成员数, 更新记录列表)
    """
    members = await team.members.all()  # type: ignore
    if not members:
        return False, 0, []
    
    all_updates: list[str] = []
    successful_members = 0
    team_updated = False
    current_scores = team.scores if team.scores else {}  # type: ignore
    
    for member in members:
        # 获取成员的 QQ 号
        qq_account = await UserAccount.get_or_none(
            user=member,
            platform=QQ_PLATFORM
        )
        
        if not qq_account:
            continue
        
        qq = qq_account.account_key
        
        # 获取 friend_code
        friend_code = await get_friend_code_by_qq(qq, dev_headers)
        if not friend_code:
            continue
        
        # 获取最近游玩记录
        recent_records = await get_recent_records(friend_code, dev_headers)
        if not recent_records:
            continue
        
        # 过滤在赛事时间范围内的记录
        filtered_records = filter_records_by_event_time(
            recent_records,
            event_start,
            event_end
        )
        
        if not filtered_records:
            continue
        
        # 验证记录
        is_valid, matched_records, _ = match_and_validate_records(
            filtered_records,
            target_songs,
            min_total_ach=97*len(target_songs)
        )
        
        if not is_valid:
            continue
        
        # 更新成绩
        new_scores, updates = update_team_scores(
            current_scores,  # type: ignore
            matched_records,
            target_songs
        )
        
        if updates:
            current_scores = new_scores
            team_updated = True
            successful_members += 1
            all_updates.extend([f"[{qq_account.account_name}]"] + updates)
    
    # 保存更新
    if team_updated:
        team.scores = current_scores  # type: ignore
        await team.save()
    
    return team_updated, successful_members, all_updates


async def auto_update_event_scores(
    event: Event,
    dev_headers: dict[str, str]
) -> tuple[int, int, dict[str, list[str]]]:
    """
    自动更新赛事所有队伍的成绩
    
    Args:
        event: 赛事对象
        dev_headers: API 请求头
    
    Returns:
        (更新的队伍数, 成功的成员数, 各队伍的更新记录)
    """
    if not event.songs:  # type: ignore
        logger.warning(f"赛事 '{event.name}' 没有设置课题曲")  # type: ignore
        return 0, 0, {}
    
    teams = await Team.filter(event=event).prefetch_related("members")
    
    updated_teams = 0
    total_members = 0
    updates_by_team: dict[str, list[str]] = {}
    
    for team in teams:
        team_updated, member_count, updates = await auto_update_team_scores(
            team,
            event.songs,  # type: ignore
            dev_headers,
            event.start_time,  # type: ignore
            event.end_time  # type: ignore
        )
        
        if team_updated:
            updated_teams += 1
            total_members += member_count
            updates_by_team[team.name] = updates
    
    return updated_teams, total_members, updates_by_team
