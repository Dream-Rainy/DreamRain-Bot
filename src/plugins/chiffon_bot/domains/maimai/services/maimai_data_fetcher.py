"""Maimai 数据拉取器 — 从 dxrating + LXNS + 柚子查拉取并合并曲库数据。"""

from __future__ import annotations

import traceback

from nonebot import logger, get_plugin_config

from ....config import Config
from ....infra.http import http_client
from ....integrations.lxns.constants import (
    maimai_song_list_url,
    maimai_alias_list_url,
    site_config_url,
    yuzuchan_maimai_alias_url,
)
from ....integrations.lxns.plugin_data import plugin_data
from ..schemas import MaiSongData, MaiSongSheet
from .map_xml_parser import (
    scan_map_directory,
    extract_music_ids_from_maps,
    scan_map_treasure_directory,
    scan_map_bonus_music_directory,
)
from .music_xml_parser import scan_music_directory
from .song_data_sync import (
    sync_mai_map_data,
    sync_mai_map_treasure_data,
)

plugin_config = get_plugin_config(Config)


def _ingame_path(sub_dir: str) -> str:
    """从 ingame_data_base_dir 推导 maimai 子目录路径。"""
    return f"{plugin_config.ingame_data_base_dir}/maimai/{sub_dir}"


async def _parse_map_xml() -> tuple[dict[int, int], dict[int, str], dict[str, int], dict[int, str]]:
    """解析本地 Map XML 数据，返回 (music_id→map_id, map_id→map_name, title→music_id, bonus_map)。"""
    music_id_to_map_id: dict[int, int] = {}
    map_id_to_map_name: dict[int, str] = {}
    title_to_music_id: dict[str, int] = {}
    music_id_to_map_name_from_bonus: dict[int, str] = {}

    base = plugin_config.ingame_data_base_dir
    if not base:
        logger.info("未配置ingame_data_base_dir，跳过Map XML解析")
        return music_id_to_map_id, map_id_to_map_name, title_to_music_id, music_id_to_map_name_from_bonus

    map_dir = _ingame_path("map")
    map_treasure_dir = _ingame_path("mapTreasure")
    map_bonus_music_dir = _ingame_path("mapBonusMusic")

    logger.info(f"开始解析Map XML文件: {map_dir}")
    maps = scan_map_directory(map_dir, map_treasure_dir)

    if maps:
        logger.info(f"成功解析 {len(maps)} 个地图数据")
        music_id_to_map_id = extract_music_ids_from_maps(
            maps, map_treasure_dir, map_bonus_music_dir,
        )
        map_id_to_map_name = {mid: m.map_name for mid, m in maps.items()}
        logger.info(f"从Map及其从属的MapTreasure提取到 {len(music_id_to_map_id)} 个music_id→map_id关联")
        logger.info("同步Map数据到数据库...")
        await sync_mai_map_data(maps)
    else:
        logger.info("未找到Map数据或解析失败")

    logger.info(f"开始解析Map的MapTreasure奖励数据: {map_treasure_dir}")
    map_treasures = scan_map_treasure_directory(map_treasure_dir)
    if map_treasures:
        logger.info(f"成功解析 {len(map_treasures)} 个Map奖励数据")
        await sync_mai_map_treasure_data(map_treasures)
        for treasure in map_treasures.values():
            if treasure.music_id and treasure.music_name:
                title_key = treasure.music_name.strip().lower()
                if title_key not in title_to_music_id:
                    title_to_music_id[title_key] = treasure.music_id
        logger.info(f"从Map奖励提取到 {len(title_to_music_id)} 个title→music_id映射")

    logger.info(f"开始解析MapBonusMusic XML文件: {map_bonus_music_dir}")
    map_bonus_musics = scan_map_bonus_music_directory(map_bonus_music_dir)
    if map_bonus_musics:
        for bonus_music in map_bonus_musics.values():
            for music_id, music_name in bonus_music.music_names.items():
                if music_name:
                    title_key = music_name.strip().lower()
                    if title_key not in title_to_music_id:
                        title_to_music_id[title_key] = music_id
                        if bonus_music.map_name:
                            music_id_to_map_name_from_bonus[music_id] = bonus_music.map_name
        logger.info(f"从MapBonusMusic补充提取后，共 {len(title_to_music_id)} 个title→music_id映射")

    return music_id_to_map_id, map_id_to_map_name, title_to_music_id, music_id_to_map_name_from_bonus


def _merge_dxrating_and_lxns(
    dxrating_data: dict,
    lxns_song_data: dict,
    dxrating_aliases_by_song_id: dict[str, list[str]],
    music_id_to_map_id: dict[int, int],
    map_id_to_map_name: dict[int, str],
    title_to_music_id: dict[str, int],
    music_id_to_map_name_from_bonus: dict[int, str],
) -> dict[int, MaiSongData]:
    """合并 dxrating 和 LXNS 数据源，以 dxrating 为主、LXNS 为补充。"""
    merged_songs: dict[int, MaiSongData] = {}

    # 构建 LXNS 索引
    lxns_by_id: dict[int, dict] = {}
    lxns_by_title: dict[str, list[dict]] = {}
    for lxns_song in lxns_song_data.get("songs", []):
        song_id = lxns_song.get("id")
        title = lxns_song.get("title")
        if song_id:
            lxns_by_id[song_id] = lxns_song
        if title:
            title_key = title.strip()
            if title_key not in lxns_by_title:
                lxns_by_title[title_key] = []
            lxns_by_title[title_key].append(lxns_song)

    dxrating_songs = dxrating_data.get("songs", []) if isinstance(dxrating_data, dict) else []
    unknown_id_counter = 10000000

    for dx_song in dxrating_songs:
        song_id_from_dx = dx_song.get("songId")
        title = dx_song.get("title")
        if not title:
            continue

        lxns_song = None
        sheets = dx_song.get("sheets", [])
        inferred_song_id = None
        associated_map_name = None

        # 优先级1: internal_id
        if sheets:
            for sheet in sheets:
                internal_id = sheet.get("internalId")
                if internal_id:
                    inferred_song_id = internal_id
                    if music_id_to_map_id and inferred_song_id in music_id_to_map_id:
                        map_id = music_id_to_map_id[inferred_song_id]
                        associated_map_name = map_id_to_map_name.get(map_id)
                    lxns_song = lxns_by_id.get(inferred_song_id)
                    break

        # 优先级2: title → music_id from Map data
        if not inferred_song_id:
            title_key = title.strip().lower()
            if title_key in title_to_music_id:
                inferred_song_id = title_to_music_id[title_key]
                lxns_song = lxns_by_id.get(inferred_song_id)

        # 优先级3: title match in LXNS
        if not lxns_song:
            title_matches = lxns_by_title.get(title.strip(), [])
            if len(title_matches) == 1:
                lxns_song = title_matches[0]
                if not inferred_song_id:
                    inferred_song_id = lxns_song.get("id")
            elif len(title_matches) > 1 and inferred_song_id:
                for candidate in title_matches:
                    if candidate.get("id") == inferred_song_id:
                        lxns_song = candidate
                        break

        # 构建 difficulties
        grouped_difficulties: dict[str, list] = {}
        is_utage_song = any(
            sheet.get("internalId", 0) > 100000
            for sheet in sheets
        )

        use_lxns_difficulties = is_utage_song and lxns_song is not None and lxns_song.get("difficulties")

        if use_lxns_difficulties and lxns_song:
            lxns_difficulties = lxns_song.get("difficulties", {})
            for diff_type, diff_list in lxns_difficulties.items():
                if diff_list:
                    diff_list[0]["version"] = dx_song.get("version")
                    sheets[0]["noteCounts"] = diff_list[0].get("notes", {})
                    sheets[0]["isBuddy"] = diff_list[0].get("is_buddy", False)
                    grouped_difficulties[diff_type] = sheets
        else:
            for s in sheets:
                t = (s.get("type") or "standard").strip().lower()
                if t == "std":
                    t = "standard"
                if s.get("noteCounts"):
                    note_counts = s["noteCounts"]
                    for key in ["tap", "hold", "slide", "touch", "break", "total"]:
                        if note_counts.get(key) is None:
                            note_counts[key] = 0
                grouped_difficulties.setdefault(t, []).append(s)

        # 定数补充
        lxns_difficulties_by_type = (
            lxns_song.get("difficulties", {})
            if lxns_song and isinstance(lxns_song.get("difficulties"), dict)
            else {}
        )
        for diff_type, diff_list in grouped_difficulties.items():
            normalized_type = (diff_type or "standard").strip().lower()
            if normalized_type == "std":
                normalized_type = "standard"
            lxns_diff_list = lxns_difficulties_by_type.get(normalized_type, [])
            for idx, sheet in enumerate(diff_list):
                if not isinstance(sheet, dict):
                    continue
                dx_internal_level_value = sheet.get("internalLevelValue")
                sheet["internalLevelValueNew"] = dx_internal_level_value
                lxns_internal = None
                if isinstance(lxns_diff_list, list) and idx < len(lxns_diff_list):
                    lxns_diff = lxns_diff_list[idx]
                    if isinstance(lxns_diff, dict):
                        lxns_internal = (
                            lxns_diff.get("internalLevelValue")
                            or lxns_diff.get("internal_level_value")
                            or lxns_diff.get("level_value")
                        )
                sheet["internalLevelValue"] = lxns_internal if lxns_internal is not None else dx_internal_level_value

        merged_song = {
            "title": title,
            "artist": dx_song.get("artist") or "",
            "bpm": dx_song.get("bpm") or 0,
            "image_name": dx_song.get("imageName") or "",
            "category": dx_song.get("category") or "",
            "version": dx_song.get("version"),
            "releaseDate": dx_song.get("releaseDate") or "",
            "isNew": dx_song.get("isNew", False),
            "isLocked": dx_song.get("isLocked", False),
            "comment": dx_song.get("comment") or "",
            "difficulties": grouped_difficulties,
        }

        if associated_map_name:
            merged_song["mai_map"] = associated_map_name

        if lxns_song:
            song_id = lxns_song.get("id")
            merged_song["id"] = song_id
            merged_song["rights"] = lxns_song.get("rights")
            if "mai_map" not in merged_song:
                merged_song["mai_map"] = lxns_song.get("map")
            if not merged_song.get("bpm"):
                merged_song["bpm"] = lxns_song.get("bpm") or 0
            if not merged_song.get("version"):
                merged_song["version"] = lxns_song.get("version")

            # CN regions mark
            lxns_diffs = (
                lxns_song.get("difficulties", {})
                if isinstance(lxns_song.get("difficulties"), dict)
                else {}
            )
            has_std = isinstance(lxns_diffs.get("standard"), list) and len(lxns_diffs.get("standard", [])) > 0
            has_dx = isinstance(lxns_diffs.get("dx"), list) and len(lxns_diffs.get("dx", [])) > 0
            for diff_type, diff_list in grouped_difficulties.items():
                ntype = (diff_type or "standard").strip().lower()
                if ntype == "std":
                    ntype = "standard"
                should_mark = (ntype == "standard" and has_std) or (ntype == "dx" and has_dx)
                for sheet in diff_list:
                    if should_mark:
                        if "regions" not in sheet or not isinstance(sheet.get("regions"), dict):
                            sheet["regions"] = {}
                        sheet["regions"]["cn"] = True
        else:
            if inferred_song_id:
                if 10000 < inferred_song_id < 100000:
                    merged_song["id"] = inferred_song_id % 10000
                else:
                    merged_song["id"] = inferred_song_id
            elif sheets:
                internal_id = sheets[0].get("internalId")
                if internal_id:
                    if 10000 < internal_id < 100000:
                        merged_song["id"] = internal_id % 10000
                    else:
                        merged_song["id"] = internal_id
                else:
                    merged_song["id"] = unknown_id_counter
                    unknown_id_counter += 1
            else:
                merged_song["id"] = unknown_id_counter
                unknown_id_counter += 1

        song_model = MaiSongData.from_dict(merged_song)

        # 附加 dxrating 别名
        initial_aliases = [song_model.title] if song_model.title else []
        if song_id_from_dx and song_id_from_dx in dxrating_aliases_by_song_id:
            initial_aliases.extend(dxrating_aliases_by_song_id[song_id_from_dx])
        song_model.aliases = initial_aliases

        merged_songs[song_model.id] = song_model

    return merged_songs


def _enrich_with_music_xml(
    merged_songs: dict[int, MaiSongData],
    music_xml_data: dict[int, dict],
) -> None:
    """将 Music.xml 数据作为补充源注入 merged_songs。

    Music.xml + ma2 为权威数据源：
    - note_counts: 权威值，直接覆盖每个谱面
    - difficulties: 如果 merged 中缺失某个难度类型（如 utage），从 XML 补充
    - 元数据: API 数据缺失时作为 fallback（含 artist / bpm）
    - title 匹配: 当 song_id 无法匹配时，尝试 title 匹配
      （远端数据更新不及时导致本地已有但远端无该 ID 的兜底）
    """
    # 构建 title → song_id 索引（title 匹配兜底）
    title_index: dict[str, int] = {}
    for sid, song in merged_songs.items():
        title_key = (song.title or "").strip().lower()
        if title_key:
            title_index[title_key] = sid

    enriched_count = 0
    title_matched_count = 0
    note_counts_written = 0
    missing_types_added = 0

    for xml_id, xml_song in music_xml_data.items():
        merged = merged_songs.get(xml_id)

        # ID 匹配失败时，尝试 title 匹配
        if merged is None:
            xml_title = (xml_song.get("title") or "").strip().lower()
            if xml_title and xml_title in title_index:
                matched_id = title_index[xml_title]
                merged = merged_songs[matched_id]
                title_matched_count += 1

        if merged is None:
            continue

        # Fallback 元数据（API 缺失时由 Music.xml 补充）
        if not getattr(merged, "category", None) and xml_song.get("category"):
            merged.category = xml_song["category"]
        if not getattr(merged, "version", None) and xml_song.get("version"):
            merged.version = xml_song["version"]
        if not getattr(merged, "rights", None) and xml_song.get("rights"):
            merged.rights = xml_song["rights"]
        if not getattr(merged, "is_locked", True) and xml_song.get("is_locked"):
            merged.is_locked = xml_song["is_locked"]
        if not getattr(merged, "comment", None) and xml_song.get("comment"):
            merged.comment = xml_song["comment"]
        if not getattr(merged, "artist", None) and xml_song.get("artist"):
            merged.artist = xml_song["artist"]
        if not getattr(merged, "bpm", None) and xml_song.get("bpm"):
            merged.bpm = xml_song["bpm"]

        # 注入 note_counts + 补充缺失的难度类型
        xml_diffs = xml_song.get("difficulties", {})
        merged_diffs = merged.difficulties

        for diff_type, xml_sheets in xml_diffs.items():
            merged_sheets = merged_diffs.get(diff_type)

            if not merged_sheets:
                # merged 中缺失该难度类型（如 utage），从 Music.xml 补充
                new_sheets: list[MaiSongSheet] = []
                for xml_sheet in xml_sheets:
                    try:
                        new_sheets.append(MaiSongSheet.model_validate(xml_sheet))
                    except Exception:
                        logger.warning(
                            f"Music XML 谱面验证失败 (id={xml_id}, type={diff_type}): "
                            f"{xml_sheet.get('difficulty', '?')}"
                        )
                if new_sheets:
                    merged_diffs[diff_type] = new_sheets
                    missing_types_added += 1
                continue

            # 注入 note_counts（ma2 解析的权威值，直接覆盖）
            for idx, xml_sheet in enumerate(xml_sheets):
                xml_nc = xml_sheet.get("note_counts")
                if xml_nc is None:
                    continue
                if idx < len(merged_sheets):
                    merged_sheets[idx].note_counts = xml_nc
                    note_counts_written += 1

        enriched_count += 1

    parts = [f"{enriched_count} 首乐曲注入了 Music XML 数据"]
    if note_counts_written:
        parts.append(f"{note_counts_written} 个谱面的 note_counts 已覆盖")
    if missing_types_added:
        parts.append(f"{missing_types_added} 个难度类型从 XML 补充")
    if title_matched_count:
        parts.append(f"{title_matched_count} 首通过 title 匹配")
    logger.info(f"Music XML 数据补充完成：{'，'.join(parts)}")


async def _attach_lxns_yuzuchan_aliases(merged_songs: dict[int, MaiSongData]) -> None:
    """拉取 LXNS + 柚子查别名并附加到 merged_songs 中。"""
    logger.info("获取 LXNS 别名数据...")
    lxns_alias_data = await http_client.get_json(maimai_alias_list_url(), force_refresh=True)
    lxns_aliases: dict[int, list[str]] = {}
    for item in lxns_alias_data.get("aliases", []):
        song_id = item.get("song_id")
        aliases = item.get("aliases", [])
        if song_id and aliases:
            lxns_aliases[song_id] = aliases
    logger.info(f"获取到 {len(lxns_aliases)} 首乐曲的 LXNS 别名")

    logger.info("获取柚子查别名数据...")
    yuzuchan_alias_data = await http_client.get_json(yuzuchan_maimai_alias_url(), force_refresh=True)
    yuzuchan_aliases: dict[int, list[str]] = {}
    for item in yuzuchan_alias_data.get("content", []):
        song_id = item.get("SongID")
        if song_id and song_id > 10000 and song_id < 100000:
            song_id = song_id % 10000
        aliases = item.get("Alias", [])
        if song_id and aliases:
            yuzuchan_aliases[song_id] = aliases
    logger.info(f"获取到 {len(yuzuchan_aliases)} 首乐曲的柚子查别名")

    all_song_ids = set(lxns_aliases.keys()) | set(yuzuchan_aliases.keys())
    for song_id in all_song_ids:
        song_info = merged_songs.get(song_id)
        if not song_info:
            continue
        additional = list(lxns_aliases.get(song_id, []))
        additional.extend(yuzuchan_aliases.get(song_id, []))
        combined = song_info.aliases + additional
        seen: set[str] = set()
        unique: list[str] = []
        for a in combined:
            a_lower = a.lower()
            if a_lower not in seen and a:
                seen.add(a_lower)
                unique.append(a)
        song_info.aliases = unique

    logger.info(f"别名合并完成，共为 {len(all_song_ids)} 首乐曲附加别名数据")


async def fetch_maimai_raw_data() -> dict[int, MaiSongData]:
    """从外部 API 拉取并合并 maimai 曲库数据（含 Map + dxrating + LXNS + 别名）。"""
    # 1. 解析本地 Map XML
    logger.info("=" * 50)
    logger.info("步骤1: 解析本地Map XML数据")
    logger.info("=" * 50)
    music_id_to_map_id, map_id_to_map_name, title_to_music_id, music_id_to_map_name_from_bonus = (
        await _parse_map_xml()
    )

    # 2. 检查在线数据版本
    logger.info("=" * 50)
    logger.info("步骤2: 检查在线数据版本")
    logger.info("=" * 50)
    data_version = await http_client.get_json(site_config_url(), force_refresh=True)
    if data_version.get("data") == plugin_data.data_version.get("data"):
        pass  # 版本未更新也继续（确保 Map XML 已同步）
    plugin_data.data_version = data_version

    # 3. 获取在线数据源
    logger.info("=" * 50)
    logger.info("步骤3: 获取在线数据源")
    logger.info("=" * 50)

    # dxrating
    logger.info("获取 dxrating original.json 数据...")
    dxrating_data = await http_client.get_json(
        "https://raw.githubusercontent.com/gekichumai/dxrating/refs/heads/main/scripts/annotator/original.json",
        force_refresh=True,
    )
    if isinstance(dxrating_data, str):
        try:
            import json
            dxrating_data = json.loads(dxrating_data)
        except Exception:
            logger.warning("dxrating original.json 返回字符串且无法解析为 JSON")
            dxrating_data = {}

    # LXNS maimai
    logger.info("获取 LXNS maimai 乐曲数据...")
    lxns_song_data = await http_client.get_json(maimai_song_list_url(notes=True), force_refresh=True)

    # dxrating aliases
    logger.info("获取 dxrating 别名数据...")
    dxrating_aliases_by_song_id: dict[str, list[str]] = {}
    try:
        dxrating_alias_data = await http_client.get_json(
            "https://miruku.dxrating.net/api/v1/aliases",
            force_refresh=True,
        )
        if isinstance(dxrating_alias_data, list):
            for item in dxrating_alias_data:
                song_id_str = item.get("song_id")
                alias_name = item.get("name")
                if song_id_str and alias_name:
                    if song_id_str not in dxrating_aliases_by_song_id:
                        dxrating_aliases_by_song_id[song_id_str] = []
                    dxrating_aliases_by_song_id[song_id_str].append(alias_name)
            logger.info(f"获取到 {len(dxrating_aliases_by_song_id)} 个song_id的 dxrating 别名")
    except Exception as e:
        logger.warning(f"获取 dxrating 别名失败: {e}")
        traceback.print_exc()

    # 4. 合并数据源
    logger.info("合并 dxrating 和 LXNS 数据源...")
    merged_songs = _merge_dxrating_and_lxns(
        dxrating_data, lxns_song_data, dxrating_aliases_by_song_id,
        music_id_to_map_id, map_id_to_map_name,
        title_to_music_id, music_id_to_map_name_from_bonus,
    )
    logger.info(f"数据合并完成：共 {len(merged_songs)} 首歌曲")

    # 5. 解析本地 Music.xml 并注入 note_counts
    if plugin_config.ingame_data_base_dir:
        logger.info("=" * 50)
        logger.info("步骤5: 解析本地Music XML数据")
        logger.info("=" * 50)
        music_dir = _ingame_path("music")
        music_xml_data = scan_music_directory(music_dir)
        if music_xml_data:
            _enrich_with_music_xml(merged_songs, music_xml_data)
        else:
            logger.info("未找到Music XML数据")

    # 6. 附加 LXNS + 柚子查别名
    await _attach_lxns_yuzuchan_aliases(merged_songs)

    return merged_songs
