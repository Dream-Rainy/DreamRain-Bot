"""CHUNITHM 数据拉取器 — 从 arcade-songs + LXNS 拉取并合并曲库数据。"""

from __future__ import annotations

import logging
from pathlib import Path

from ...core.context import CatalogContext
from ...integrations.lxns.constants import (
    chunithm_song_list_url,
    chunithm_alias_list_url,
)
from .schemas import ChuniSongData
from .music_xml_parser import scan_music_directory

ARCADE_SITES_JSON_URL = (
    "https://raw.githubusercontent.com/zetaraku/arcade-songs/master/data/sites.json"
)

_CHUNI_REMOTE_ASSETS_BASE_URL = "https://assets2.lxns.net/chunithm"

_CHUNI_LXNS_LEVEL_TO_LABEL: dict[int, str] = {
    0: "basic",
    1: "advanced",
    2: "expert",
    3: "master",
    4: "ultima",
}


# ══════════════════════════════════════════════════════════════════════════
# arcade-songs 数据源
# ══════════════════════════════════════════════════════════════════════════

async def _fetch_arcade_data_json(context: CatalogContext, gamecode: str) -> dict:
    """从 arcade-songs 的 sites.json 解析 data.json URL 并拉取 payload。"""
    import json

    sites = await context.get_json(ARCADE_SITES_JSON_URL, force_refresh=True)
    if isinstance(sites, str):
        try:
            sites = json.loads(sites)
        except Exception:
            sites = []

    base_url = ""
    if isinstance(sites, list):
        for site in sites:
            if isinstance(site, dict) and site.get("gameCode") == gamecode:
                base_url = (site.get("dataSourceUrl") or "").rstrip("/")
                break

    if not base_url:
        raise ValueError(f"arcade-songs sites.json 中未找到 {gamecode} 的 dataSourceUrl")

    data_url = f"{base_url}/data.json"
    payload = await context.get_json(data_url, force_refresh=True)
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception as exc:
            raise ValueError(f"{gamecode} data.json 返回非 JSON") from exc
    if not isinstance(payload, dict):
        return {}
    return payload


# ══════════════════════════════════════════════════════════════════════════
# LXNS / arcade 合并辅助函数
# ══════════════════════════════════════════════════════════════════════════

def _lxns_is_we(lxns_song: dict) -> bool:
    """判断 LXNS Chunithm 曲目是否为 World's End。"""
    lid = lxns_song.get("id")
    try:
        if lid is not None and int(lid) > 8000:
            return True
    except (TypeError, ValueError):
        pass
    diffs = lxns_song.get("difficulties")
    if isinstance(diffs, list):
        return any(
            isinstance(d, dict) and d.get("difficulty") == 5
            for d in diffs
        )
    if isinstance(diffs, dict):
        if diffs.get("we") or diffs.get("worldsend"):
            return True
        for lst in diffs.values():
            if not isinstance(lst, list):
                continue
            for d in lst:
                if isinstance(d, dict) and d.get("difficulty") == 5:
                    return True
    return False


def _arc_is_we(arc_song: dict) -> bool:
    """arcade-songs：category 为 WORLD'S END 时为 WE 曲。"""
    return (arc_song.get("category") or "").strip().upper() == "WORLD'S END"


def _lxns_chuni_difficulties_as_map(lxns_song: dict | None) -> dict:
    """将 LXNS Chunithm difficulties 转为按 type 分组字典。"""
    if not lxns_song:
        return {}
    diffs = lxns_song.get("difficulties")
    if isinstance(diffs, dict):
        return diffs
    if not isinstance(diffs, list):
        return {}
    standard: list[dict] = []
    ultima: list[dict] = []
    we: list[dict] = []
    for d in diffs:
        if not isinstance(d, dict):
            continue
        di = d.get("difficulty")
        try:
            di_int = int(di) if di is not None else -1
        except (TypeError, ValueError):
            di_int = -1
        if di_int == 5:
            we.append(d)
        elif di_int == 4:
            ultima.append(d)
        elif di_int >= 0:
            standard.append(d)
        else:
            standard.append(d)

    def _sort_key(x: dict) -> int:
        di = x.get("difficulty")
        try:
            return int(di) if di is not None else 999
        except (TypeError, ValueError):
            return 999

    standard.sort(key=_sort_key)
    ultima.sort(key=_sort_key)
    out: dict = {}
    if standard:
        out["standard"] = standard
    if ultima:
        out["ultima"] = ultima
    if we:
        out["we"] = we
    return out


def _chuni_sheet_dict_from_lxns_row(lxns_row: dict, bucket: str) -> dict:
    """由 LXNS 单条难度数据生成与 arcade-songs 结构兼容的谱面 dict。"""
    bucket_l = (bucket or "").strip().lower()
    notes = lxns_row.get("notes") or {}
    if not isinstance(notes, dict):
        notes = {}
    nc: dict[str, int] = {}
    for key in ("tap", "hold", "slide", "touch", "break", "air", "flick", "total"):
        v = notes.get(key)
        if v is None:
            nc[key] = 0
        else:
            try:
                nc[key] = int(v)
            except (TypeError, ValueError):
                try:
                    nc[key] = int(float(v))
                except (TypeError, ValueError):
                    nc[key] = 0
    lv = lxns_row.get("level_value")
    if lv is None:
        lv = lxns_row.get("internal_level_value")

    di = lxns_row.get("difficulty")
    if bucket_l in ("we", "worldsend"):
        diff_label = lxns_row.get("kanji") or lxns_row.get("level") or "we"
        raw_t = "we"
    else:
        try:
            di_int = int(di) if di is not None else 0
        except (TypeError, ValueError):
            di_int = 0
        diff_label = _CHUNI_LXNS_LEVEL_TO_LABEL.get(di_int, str(lxns_row.get("level") or ""))
        raw_t = "std"

    designer = lxns_row.get("note_designer")
    if designer is None:
        designer = lxns_row.get("noteDesigner")

    return {
        "type": raw_t,
        "difficulty": diff_label,
        "level": str(lxns_row.get("level") or ""),
        "levelValue": lv,
        "internalLevelValue": lv,
        "internalLevelValueNew": None,
        "noteDesigner": designer if designer is not None else "-",
        "noteCounts": nc,
        "regions": {},
    }


def _group_arcade_chuni_sheets(arc_song: dict | None, chuni_note_keys: tuple[str, ...]) -> dict[str, list]:
    """将 arcade 谱面按 type 分组。"""
    grouped: dict[str, list] = {}
    if not arc_song:
        return grouped
    for s in arc_song.get("sheets") or []:
        if not isinstance(s, dict):
            continue
        raw_t = (s.get("type") or "std").strip().lower()
        t = "standard" if raw_t == "std" else raw_t
        if s.get("noteCounts"):
            nc = s["noteCounts"]
            for key in chuni_note_keys:
                if key in nc and nc.get(key) is None:
                    nc[key] = 0
        grouped.setdefault(t, []).append(s)
    return grouped


def _ingame_path(context: CatalogContext, sub_dir: str) -> str:
    return context.ingame_path("chunithm", sub_dir)


def build_chuni_jacket_image_name(
    song_id: object,
    jacket_file_path: str | None = "",
    *,
    remote_assets_base_url: str | None = None,
) -> str:
    """生成模板可直接使用的 CHUNITHM 封面 src。"""
    if jacket_file_path:
        filename = Path(str(jacket_file_path).strip()).name
        if filename:
            path = Path(filename)
            if path.suffix.lower() == ".dds":
                filename = f"{path.stem}.png"
            return f"jacket/{filename}"

    try:
        parsed_song_id = int(song_id)
    except (TypeError, ValueError):
        parsed_song_id = None

    if parsed_song_id is not None and parsed_song_id > 0:
        assets_base = (remote_assets_base_url or _CHUNI_REMOTE_ASSETS_BASE_URL).rstrip("/")
        return f"{assets_base}/jacket/{parsed_song_id}.png"

    return ""


def _resolve_arcade_title_conflict(
    lxns_song: dict,
    candidates: list[dict],
    logger=None,
) -> dict | None:
    """当多条 arcade 与同一 LXNS 标题匹配时消歧。"""
    logger = logger or logging.getLogger(__name__)
    lx_artist = (lxns_song.get("artist") or "").strip().lower()

    if lx_artist:
        by_artist = [
            c for c in candidates
            if (c.get("artist") or "").strip().lower() == lx_artist
        ]
        if len(by_artist) == 1:
            return by_artist[0]
        if by_artist:
            candidates = by_artist

    lx_we = _lxns_is_we(lxns_song)
    if lx_we:
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]
        logger.debug(
            f"chunithm: 标题 {lxns_song.get('title')!r} 对应多条 arcade 非 WE 记录，"
            "取 songId 最小项作为元数据补充"
        )
        return sorted(candidates, key=lambda x: str(x.get("songId") or ""))[0]

    by_type = [c for c in candidates if not _arc_is_we(c)]
    if len(by_type) == 1:
        return by_type[0]
    if len(by_type) > 1:
        logger.warning(
            f"chunithm: LXNS id={lxns_song.get('id')} 标题 {lxns_song.get('title')!r} "
            f"在 arcade 有 {len(by_type)} 条非 WE 匹配，曲师无法区分，取 songId 最小项"
        )
        return sorted(by_type, key=lambda x: str(x.get("songId") or ""))[0]
    return None


# ══════════════════════════════════════════════════════════════════════════
# 主合并与拉取入口
# ══════════════════════════════════════════════════════════════════════════

def merge_chuni_arcade_and_lxns(
    arcade_payload: dict,
    lxns_payload: dict,
    music_xml_data: dict[int, dict] | None = None,
    logger=None,
) -> dict[int, ChuniSongData]:
    """以 LXNS 为主源、arcade-songs 为补充；跳过 arcade 的 WORLD'S END 条目。"""
    arcade_by_title: dict[str, list[dict]] = {}
    for arc_song in arcade_payload.get("songs", []):
        if not isinstance(arc_song, dict):
            continue
        if _arc_is_we(arc_song):
            continue
        t = arc_song.get("title")
        if not t:
            continue
        key = str(t).strip()
        arcade_by_title.setdefault(key, []).append(arc_song)

    merged_chuni: dict[int, ChuniSongData] = {}
    unknown_id_counter = 100000
    chuni_note_keys = ("tap", "hold", "slide", "touch", "break", "air", "flick", "total")
    music_xml_data = music_xml_data or {}

    for lxns_song in lxns_payload.get("songs", []):
        if not isinstance(lxns_song, dict):
            continue
        title = lxns_song.get("title")
        if not title:
            continue

        title_key = str(title).strip()
        if lxns_song.get("id") is not None:
            try:
                inferred_song_id = int(lxns_song["id"])
            except (TypeError, ValueError):
                inferred_song_id = unknown_id_counter
                unknown_id_counter += 1
        else:
            inferred_song_id = unknown_id_counter
            unknown_id_counter += 1

        arc_candidates = list(arcade_by_title.get(title_key, []))
        arc_song: dict | None = None
        if len(arc_candidates) == 1:
            arc_song = arc_candidates[0]
        elif len(arc_candidates) > 1:
            arc_song = _resolve_arcade_title_conflict(lxns_song, arc_candidates, logger)

        lxns_diff_map = _lxns_chuni_difficulties_as_map(lxns_song)
        grouped_difficulties: dict[str, list] = {}
        for map_key, rows in lxns_diff_map.items():
            if not isinstance(rows, list) or not rows:
                continue
            norm = str(map_key).strip().lower()
            if norm == "std":
                norm = "standard"
            bucket = norm
            for row in rows:
                if not isinstance(row, dict):
                    continue
                grouped_difficulties.setdefault(bucket, []).append(
                    _chuni_sheet_dict_from_lxns_row(row, bucket)
                )

        arc_grouped = _group_arcade_chuni_sheets(arc_song, chuni_note_keys)

        for _diff_type, diff_list in grouped_difficulties.items():
            normalized_type = ((_diff_type or "standard") or "standard").strip().lower()
            if normalized_type == "std":
                normalized_type = "standard"
            arc_list = arc_grouped.get(normalized_type, [])
            if not arc_list and normalized_type == "standard" and "std" in arc_grouped:
                arc_list = arc_grouped.get("std", [])

            for idx, sheet in enumerate(diff_list):
                if not isinstance(sheet, dict):
                    continue
                lv_lxns = sheet.get("internalLevelValue")
                arc_internal = None
                if isinstance(arc_list, list) and idx < len(arc_list):
                    a = arc_list[idx]
                    if isinstance(a, dict):
                        arc_internal = a.get("internalLevelValue")
                        ar = a.get("regions")
                        if isinstance(ar, dict):
                            base_r = sheet.setdefault("regions", {})
                            for rk, rv in ar.items():
                                if rk != "cn":
                                    base_r[rk] = rv
                sheet["internalLevelValue"] = lv_lxns
                sheet["internalLevelValueNew"] = arc_internal

        for _, diff_list in grouped_difficulties.items():
            for sheet in diff_list:
                if not isinstance(sheet, dict):
                    continue
                sheet.setdefault("regions", {})
                sheet["regions"]["cn"] = True

        genre_lx = lxns_song.get("genre") or ""
        bpm_val = lxns_song.get("bpm")
        if bpm_val is None and arc_song is not None:
            bpm_val = arc_song.get("bpm")
        if bpm_val is None:
            bpm_val = 0

        artist = (lxns_song.get("artist") or (arc_song.get("artist") if arc_song else "") or "")

        category = genre_lx or ((arc_song.get("category") if arc_song else "") or "")

        is_locked = arc_song.get("isLocked") if arc_song else None
        if is_locked is None:
            is_locked = False
        xml_song = music_xml_data.get(inferred_song_id) or {}

        merged_song = ChuniSongData.model_validate({
            "id": inferred_song_id,
            "title": title_key,
            "artist": artist,
            "bpm": bpm_val,
            "image_name": build_chuni_jacket_image_name(
                inferred_song_id,
                xml_song.get("image_name") or "",
            ),
            "genre": genre_lx or category,
            "version": lxns_song.get("version"),
            "release_date": (arc_song.get("releaseDate") if arc_song else "") or "",
            "is_new": bool(arc_song.get("isNew", False)) if arc_song else False,
            "is_locked": bool(is_locked),
            "comment": (arc_song.get("comment") if arc_song else "") or "",
            "rights": lxns_song.get("rights"),
            "difficulties": grouped_difficulties,
            "songId": arc_song.get("songId") if arc_song else None,
        })
        merged_chuni[inferred_song_id] = merged_song

    return merged_chuni


async def fetch_chunithm_catalog(context: CatalogContext) -> dict[int, ChuniSongData]:
    """从外部 API 拉取并合并 CHUNITHM 曲库数据（含别名）。"""
    logger = context.logger
    logger.info("获取 chunithm 数据（arcade-songs + LXNS）...")
    music_xml_data: dict[int, dict] = {}
    if context.ingame_data_base_dir:
        music_xml_data = scan_music_directory(_ingame_path(context, "music"))
    arcade_chuni = await _fetch_arcade_data_json(context, "chunithm")
    chuni_lxns = await context.get_json(
        chunithm_song_list_url(notes=True), force_refresh=True
    )
    if not isinstance(chuni_lxns, dict):
        chuni_lxns = {"songs": []}
    merged = merge_chuni_arcade_and_lxns(arcade_chuni, chuni_lxns, music_xml_data, logger)
    logger.info(f"chunithm 合并完成：共 {len(merged)} 首")

    # 获取 LXNS chunithm 别名并附加
    logger.info("获取 chunithm 乐曲别名（LXNS）...")
    alias_data = await context.get_json(chunithm_alias_list_url(), force_refresh=True)
    lxns_aliases: dict[int, list[str]] = {}
    for item in (alias_data.get("aliases") or []):
        song_id = item.get("song_id")
        aliases = item.get("aliases") or []
        if song_id and aliases:
            lxns_aliases[int(song_id)] = aliases
    logger.info(f"获取到 {len(lxns_aliases)} 首乐曲的 chunithm LXNS 别名")

    for song_id, song in merged.items():
        title = song.title or ""
        extra = lxns_aliases.get(song_id) or []
        combined = ([title] if title else []) + extra
        seen: set[str] = set()
        unique: list[str] = []
        for a in combined:
            if a and a.lower() not in seen:
                seen.add(a.lower())
                unique.append(a)
        song.aliases = unique

    return merged


__all__ = [
    "build_chuni_jacket_image_name",
    "fetch_chunithm_catalog",
    "merge_chuni_arcade_and_lxns",
]
