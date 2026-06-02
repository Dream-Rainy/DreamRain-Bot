"""Music.xml 解析器 — 解析 in-game Music.xml 文件提取乐曲数据。

从 Music.xml 提取的字段对应 MaiSongData schema 的可映射子集。
对于每个启用的谱面，调用 ma2_parser 获取 note 数量统计。
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from nonebot import logger

from .ma2_parser import parse_ma2

# Notes 索引 → 难度名称
_DIFFICULTY_NAMES = ["basic", "advanced", "expert", "master", "remaster"]


def _parse_id_str(element: ET.Element | None) -> tuple[int | None, str | None]:
    """解析包含 <id> 和 <str> 子元素的 XML 元素。"""
    if element is None:
        return None, None
    id_elem = element.find("id")
    str_elem = element.find("str")
    id_val = None
    if id_elem is not None and id_elem.text:
        try:
            id_val = int(id_elem.text)
        except ValueError:
            pass
    str_val = str_elem.text if str_elem is not None and str_elem.text else None
    return id_val, str_val


def _build_level_display(level: int, level_decimal: int) -> str:
    """构造难度等级显示字符串。"""
    return f"{level}+" if level_decimal > 0 else str(level)


def parse_music_xml(xml_path: str | Path) -> dict[str, Any] | None:
    """解析单个 Music.xml 文件，返回与 MaiSongData 兼容的字典。

    Args:
        xml_path: Music.xml 文件路径

    Returns:
        乐曲数据字典，解析失败返回 None
    """
    try:
        tree = ET.parse(str(xml_path))
        root = tree.getroot()
    except Exception as e:
        logger.error(f"解析 Music.xml 失败 ({xml_path}): {e}")
        return None

    try:
        # 基本信息
        data_name = root.findtext("dataName", "")

        # name → id, title
        song_id, title = _parse_id_str(root.find("name"))
        if song_id is None or not title:
            logger.warning(f"Music.xml 缺少 name/id 或 name/str: {xml_path}")
            return None
        
        is_dx = 10000 <= song_id < 100000

        # artist
        _, artist = _parse_id_str(root.find("artistName"))
        artist = artist or ""

        # category (genre)
        _, category = _parse_id_str(root.find("genreName"))

        # bpm
        bpm_text = root.findtext("bpm", "0")
        bpm = float(bpm_text) if bpm_text else 0.0

        # version: 使用 AddVersion/str
        _, version = _parse_id_str(root.find("AddVersion"))

        # rights
        _, rights = _parse_id_str(root.find("rightsInfoName"))

        # is_locked
        lock_type_text = root.findtext("lockType", "0")
        is_locked = lock_type_text != "0"

        # comment
        comment_elem = root.find("comment")
        comment = ""
        if comment_elem is not None and comment_elem.text:
            comment = comment_elem.text.strip()

        # 判断是否为宴谱
        utage_kanji = root.findtext("utageKanjiName", "")
        is_utage = bool(utage_kanji)
        cue_name_id, _ = _parse_id_str(root.find("cueName"))

        # 解析 notesData → difficulties
        difficulties: dict[str, list[dict[str, Any]]] = {}
        ma2_dir = Path(xml_path).parent

        notes_data = root.find("notesData")
        if notes_data is not None:
            for idx, notes_elem in enumerate(notes_data.findall("Notes")):
                is_enable = notes_elem.findtext("isEnable", "false").lower() == "true"
                if not is_enable:
                    continue

                level_text = notes_elem.findtext("level", "0")
                level = int(level_text) if level_text else 0

                level_dec_text = notes_elem.findtext("levelDecimal", "0")
                level_decimal = int(level_dec_text) if level_dec_text else 0

                level_value = level + level_decimal / 10.0

                _, note_designer = _parse_id_str(notes_elem.find("notesDesigner"))

                music_level_id_text = notes_elem.findtext("musicLevelID", "0")
                music_level_id = int(music_level_id_text) if music_level_id_text else 0

                # 获取 ma2 文件路径并解析 note 数量
                note_counts: dict[str, int] | None = None
                file_elem = notes_elem.find("file")
                if file_elem is not None:
                    ma2_path = file_elem.findtext("path", "")
                    if ma2_path:
                        full_ma2_path = ma2_dir / ma2_path
                        if full_ma2_path.exists():
                            counts = parse_ma2(full_ma2_path)
                            note_counts = counts.to_dict()

                difficulty_name = (
                    _DIFFICULTY_NAMES[idx]
                    if idx < len(_DIFFICULTY_NAMES)
                    else f"chart_{idx}"
                )
                # 宴谱类型使用 "utage"，普通使用 "standard"
                if is_utage:
                    sheet_type = "utage"
                elif is_dx:
                    sheet_type = "dx"
                else:
                    sheet_type = "standard"

                sheet: dict[str, Any] = {
                    "type": sheet_type,
                    "difficulty": difficulty_name,
                    "level": _build_level_display(level, level_decimal),
                    "level_value": level_value,
                    "note_designer": note_designer,
                    "note_counts": note_counts,
                    "internal_id": music_level_id if music_level_id > 0 else None,
                    "is_special": False,
                }
                difficulties.setdefault(sheet_type, []).append(sheet)

        return {
            "id": song_id,
            "title": title,
            "artist": artist,
            "bpm": bpm,
            "category": category,
            "version": version,
            "rights": rights,
            "is_locked": is_locked,
            "comment": comment,
            "difficulties": difficulties,
            "cue_name_id": cue_name_id,
            "image_name": "",
            "aliases": [],
        }
    except Exception as e:
        logger.error(f"解析 Music.xml 字段失败 ({xml_path}): {e}")
        return None


def scan_music_directory(music_base_dir: str | Path) -> dict[int, dict[str, Any]]:
    """递归扫描 music 目录，解析所有 Music.xml 文件。

    Args:
        music_base_dir: music 文件夹基础路径

    Returns:
        {song_id: song_dict} 字典
    """
    result: dict[int, dict[str, Any]] = {}
    base_path = Path(music_base_dir)
    if not base_path.exists() or not base_path.is_dir():
        logger.warning(f"Music 目录不存在或不可访问: {music_base_dir}")
        return result

    logger.info(f"开始扫描 Music 目录: {music_base_dir}")
    count = 0
    for music_xml_path in base_path.rglob("Music.xml"):
        song_dict = parse_music_xml(music_xml_path)
        if song_dict:
            song_id = song_dict["id"]
            if 10000 <= song_id < 100000:
                song_id %= 10000
            result[song_id] = song_dict
            count += 1
            logger.debug(
                f"解析 Music.xml: id={song_id}, title={song_dict['title']}"
            )

    logger.info(f"Music 目录扫描完成，共解析 {count} 首乐曲")
    return result
