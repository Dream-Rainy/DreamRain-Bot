"""赛事成绩处理逻辑"""
from __future__ import annotations

from datetime import datetime
from typing import Any

LONG_DURATION_SONGS:  set[str] = {
    "Xaleid◆scopiX",
    "Ref:rain (for 7th Heaven)"
}


def _parse_play_time(time_str: str | None) -> datetime | None: 
    """解析 ISO 8601 格式时间"""
    if not time_str: 
        return None
    try: 
        return datetime.fromisoformat(time_str.replace("Z", "+00:00"))
    except:
        import traceback
        traceback.print_exc()
        return None


def _is_long_duration_song(record: dict[str, Any]) -> bool:
    """判断是否为长曲目"""
    song_name = record.get("song_name", "")
    return song_name in LONG_DURATION_SONGS


def _is_same_round(
    records: list[dict[str, Any]],
    gap_threshold_minutes: int = 6,
    long_song_gap_threshold_minutes: int = 10
) -> bool:
    """
    验证一组记录是否属于同一轮
    
    条件：
    1. upload_time 相同
    2. 相邻记录的 play_time 间隔在阈值内
    
    Args:
        records: 候选记录列表（按时间倒序）
        gap_threshold_minutes: 普通曲目的时间间隔阈值
        long_song_gap_threshold_minutes: 长曲目的时间间隔阈值
    
    Returns: 
        是否属于同一轮
    """
    if len(records) < 2:
        return True
    
    # 检查 upload_time 是否相同
    upload_times = [r.get("upload_time") for r in records if r.get("upload_time")]
    if upload_times and len(set(upload_times)) > 1:
        return False
    
    # 检查 play_time 间隔
    for i in range(len(records) - 1):
        curr_record = records[i]
        next_record = records[i + 1]
        
        curr_time = _parse_play_time(curr_record.get("play_time"))
        next_time = _parse_play_time(next_record.get("play_time"))
        
        if curr_time and next_time: 
            # 记录按时间倒序，curr_time > next_time
            gap_minutes = (curr_time - next_time).total_seconds() / 60
            
            # 根据下一条记录（时间更早的那首歌）是否为长曲目选择阈值
            if _is_long_duration_song(next_record):
                threshold = long_song_gap_threshold_minutes
            else:
                threshold = gap_threshold_minutes
            
            if gap_minutes > threshold:
                return False
    
    return True

def _get_best_records_from_rounds(
    valid_rounds: list[list[dict[str, Any]]],
    target_songs: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """
    从所有有效轮次中，为每首课题曲选取最高成绩
    
    Args:
        valid_rounds: 有效轮次列表
        target_songs: 课题曲列表（按顺序）
    
    Returns:
        每首课题曲的最高成绩记录列表（按课题曲顺序）
    """
    num_songs = len(target_songs)
    
    # 为每首课题曲维护最高成绩记录
    best_records:  list[dict[str, Any] | None] = [None] * num_songs
    
    for round_records in valid_rounds:
        for idx, record in enumerate(round_records):
            current_best = best_records[idx]
            
            if current_best is None: 
                best_records[idx] = record
            else:
                # 比较成绩：优先 achievements，相同则比较 dx_score
                new_ach = record.get("achievements", 0)
                old_ach = current_best. get("achievements", 0)
                
                if new_ach > old_ach:
                    best_records[idx] = record
                elif new_ach == old_ach:
                    new_dx = record.get("dx_score", 0)
                    old_dx = current_best.get("dx_score", 0)
                    if new_dx > old_dx: 
                        best_records[idx] = record
    
    # 过滤掉 None（理论上不应该有）
    return [r for r in best_records if r is not None]


def find_valid_rounds(
    records: list[dict[str, Any]],
    target_songs: list[dict[str, Any]],
    gap_threshold_minutes: int = 6,
    long_song_gap_threshold_minutes: int = 10
) -> list[list[dict[str, Any]]]: 
    """
    找出所有有效的轮次
    
    步骤：
    1. 筛选出课题曲记录
    2. 按顺序分组（每3条为一组，顺序需匹配课题曲顺序）
    3. 验证每组是否属于同一轮（upload_time 相同，play_time 间隔合理）
    
    Args:
        records: 按时间倒序排列的游玩记录
        target_songs: 课题曲列表（按游玩顺序排列）
        gap_threshold_minutes: 普通曲目的时间间隔阈值
        long_song_gap_threshold_minutes: 长曲目的时间间隔阈值
    
    Returns:
        有效轮次列表，每个轮次包含匹配的记录
    """
    if not records or not target_songs:
        return []
    
    # 获取课题曲ID顺序
    target_song_ids = [
        song.get("song_id") or song.get("id")
        for song in target_songs
    ]
    target_set = set(target_song_ids)
    num_songs = len(target_songs)
    
    # 第一步：筛选课题曲记录，保留原始顺序
    filtered:  list[dict[str, Any]] = []
    for record in records:
        song_id = record.get("song_id") or record.get("id")
        if song_id in target_set:
            filtered.append(record)
    
    if len(filtered) < num_songs:
        return []
    
    
    # 第二步：按顺序匹配，寻找符合课题曲顺序的连续序列
    valid_rounds:  list[list[dict[str, Any]]] = []
    i = 0
    
    while i <= len(filtered) - num_songs:
        candidate = filtered[i: i + num_songs]

        
        # 检查顺序是否匹配课题曲顺序
        candidate_ids = [
            r.get("song_id") or r.get("id")
            for r in candidate
        ]
        
        if candidate_ids == target_song_ids[::-1]:
            # 顺序正确，验证是否属于同一轮
            if _is_same_round(
                candidate,
                gap_threshold_minutes,
                long_song_gap_threshold_minutes
            ):
                valid_rounds.append(candidate)
                i += num_songs  # 跳过已匹配的记录
                continue
        
        i += 1
    
    return valid_rounds


def match_and_validate_records(
    records: list[dict[str, Any]],
    target_songs:  list[dict[str, Any]],
    max_time_diff: int = 5,
    min_total_ach: float = 291.0
) -> tuple[bool, list[dict[str, Any]], str]:
    """
    记录匹配逻辑：先筛选课题曲，再按顺序匹配验证
    
    Args: 
        records: 按时间倒序排列的游玩记录
        target_songs:  课题曲列表（按游玩顺序排列）
        max_time_diff: 同一轮内最大时间间隔（分钟）
        min_total_ach: 最低总达成率要求
    
    Returns:
        (是否有效, 匹配的记录列表, 错误信息)
    """
    if not records: 
        return False, [], "没有游玩记录"
    
    if not target_songs:
        return False, [], "没有设置课题曲"
    
    # 找出所有有效轮次
    valid_rounds = find_valid_rounds(
        records,
        target_songs,
        gap_threshold_minutes=max_time_diff
    )
    
    if not valid_rounds:
        return False, [], "未找到有效的完整轮次"
    
    # 过滤满足最低达成率要求的轮次
    qualified_rounds = [
        round_records for round_records in valid_rounds
        if sum(r.get("achievements", 0) for r in round_records) >= min_total_ach
    ]
    
    if not qualified_rounds:
        return False, [], "没有满足达成率要求的轮次"
    
    # 从所有满足条件的轮次中，为每首课题曲选取最高成绩
    best_records = _get_best_records_from_rounds(qualified_rounds, target_songs)
    
    if len(best_records) != len(target_songs):
        return False, [], "匹配记录数量不正确"
    
    return True, best_records, ""


def match_song(play_record: dict[str, Any], target_song: dict[str, Any]) -> bool:
    """
    检查游玩记录是否匹配课题曲
    
    Args:
        play_record: 游玩记录，包含 id, level, level_index, type
        target_song: 课题曲，包含 id, level, level_index, type
    
    Returns:
        是否完全匹配
    """
    return (
        play_record.get("id") == target_song.get("id")
        and play_record.get("level") == target_song.get("level")
        and play_record.get("level_index") == target_song.get("level_index")
        and play_record.get("type") == target_song.get("type")
    )


def validate_total_achievements(
    play_records: list[dict[str, Any]], 
    min_total: float = 295.0
) -> tuple[bool, float]:
    """
    验证总成绩是否达标
    
    Args:
        play_records: 游玩记录列表
        min_total: 最低总成绩要求
    
    Returns:
        (是否达标, 实际总成绩)
    """
    total = sum(record.get("achievements", 0) for record in play_records)
    return total >= min_total, total


def should_update_score(
    new_record: dict[str, Any],
    old_record: dict[str, Any] | None
) -> bool:
    """
    判断是否应该更新成绩
    
    规则：
    1. 如果没有旧记录，直接更新
    2. 如果新 achievements > 旧 achievements，更新
    3. 如果 achievements 相同但新 dx_score > 旧 dx_score，更新
    
    Args: 
        new_record: 新游玩记录
        old_record: 旧成绩记录（可能为 None）
    
    Returns: 
        是否应该更新
    """
    if old_record is None:
        return True
    
    new_ach = new_record.get("achievements", 0)
    old_ach = old_record.get("achievements", 0)
    
    if new_ach > old_ach:
        return True
    
    if new_ach == old_ach: 
        new_dx = new_record.get("dx_score", 0)
        old_dx = old_record.get("dx_score", 0)
        return new_dx > old_dx
    
    return False


def format_song_key(song: dict[str, Any]) -> str:
    """生成歌曲的唯一键"""
    return f"{song['id']}_{song['level']}_{song['level_index']}_{song['type']}"


def update_team_scores(
    team_scores: dict[str, dict[str, Any]],
    matched_records: list[dict[str, Any]],
    target_songs: list[dict[str, Any]]
) -> tuple[dict[str, dict[str, Any]], list[str]]: 
    """
    更新队伍成绩
    
    Args:
        team_scores:  当前队伍成绩字典
        matched_records: 匹配的游玩记录
        target_songs: 课题曲列表
    
    Returns:
        (更新后的成绩字典, 更新记录列表)
    """
    new_scores = team_scores.copy()
    updates = []

    # ===== 构建 record 的字典映射 =====
    records_dict = {}
    for record in matched_records:
        song_id = record.get("song_id") or record.get("id")
        if song_id:
            records_dict[song_id] = record
    # ==================================

    for target_song in target_songs:
        target_song_id = target_song.get("song_id") or target_song.get("id")
        
        # ===== 通过ID查找对应的 record =====
        record = records_dict.get(target_song_id)
        if not record:
            print(f"警告：未找到歌曲 {target_song.get('song_name')} 的成绩记录")
            continue
        # ===================================
        
        song_key = format_song_key(target_song)
        old_record = new_scores.get(song_key)
        
        if should_update_score(record, old_record):
            new_scores[song_key] = {
                "achievements": record.get("achievements"),
                "dx_score": record.get("dx_score"),
                "song_name": target_song.get("song_name"),
                "level": target_song.get("level"),
                "level_index": target_song.get("level_index"),
                "type": target_song.get("type"),
                "play_time": record.get("play_time"),
            }
            
            ach = record.get("achievements", 0)
            dx = record.get("dx_score", 0)
            song_name = target_song.get("song_name", "未知")
            
            if old_record:
                old_ach = old_record.get("achievements", 0)
                old_dx = old_record.get("dx_score", 0)
                updates.append(
                    f"  {song_name}: {old_ach:.4f}%→{ach:.4f}% (DX: {old_dx}→{dx})"
                )
            else:
                updates.append(
                    f"  {song_name}: {ach:.4f}% (DX: {dx}) [新记录]"
                )

    return new_scores, updates