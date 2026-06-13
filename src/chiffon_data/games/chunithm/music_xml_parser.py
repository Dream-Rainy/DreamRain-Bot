"""CHUNITHM Music.xml 解析器。"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import logging

logger = logging.getLogger(__name__)


def _parse_id(element: ET.Element | None) -> int | None:
    if element is None:
        return None
    text = element.findtext("id")
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _normalize_jacket_path(path_text: str | None) -> str:
    if not path_text:
        return ""
    source = Path(path_text.strip()).name
    if not source:
        return ""
    source_path = Path(source)
    filename = f"{source_path.stem}.png" if source_path.suffix.lower() == ".dds" else source
    return f"jacket/{filename}"


def parse_music_xml(xml_path: str | Path) -> dict[str, Any] | None:
    """解析单个 CHUNITHM Music.xml，返回封面相关元数据。"""
    try:
        tree = ET.parse(str(xml_path))
        root = tree.getroot()
    except Exception as e:
        logger.error(f"解析 CHUNITHM Music.xml 失败 ({xml_path}): {e}")
        return None

    song_id = _parse_id(root.find("name"))
    if song_id is None:
        logger.warning(f"CHUNITHM Music.xml 缺少 name/id: {xml_path}")
        return None

    return {
        "id": song_id,
        "image_name": _normalize_jacket_path(root.findtext("jaketFile/path")),
    }


def scan_music_directory(music_base_dir: str | Path) -> dict[int, dict[str, Any]]:
    """递归扫描 CHUNITHM music 目录，提取 Music.xml 中的封面文件名。"""
    result: dict[int, dict[str, Any]] = {}
    base_path = Path(music_base_dir)
    if not base_path.exists() or not base_path.is_dir():
        logger.warning(f"CHUNITHM Music 目录不存在或不可访问: {music_base_dir}")
        return result

    logger.info(f"开始扫描 CHUNITHM Music 目录: {music_base_dir}")
    for music_xml_path in base_path.rglob("Music.xml"):
        song_dict = parse_music_xml(music_xml_path)
        if not song_dict:
            continue
        result[song_dict["id"]] = song_dict

    logger.info(f"CHUNITHM Music 目录扫描完成，共解析 {len(result)} 首乐曲")
    return result
