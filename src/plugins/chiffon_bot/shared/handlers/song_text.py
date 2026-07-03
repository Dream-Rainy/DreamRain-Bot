"""Text song detail and jacket helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

from nonebot import logger

from arcade_helper.search import SongQueryResult

from ...infra.http import http_client


def format_song_text_detail(game_code: str, result: SongQueryResult) -> list[str]:
    song = result.song_data
    lines = [
        f"[{game_code}] 曲目详情",
        f"曲名: {result.title} ({result.song_id})",
    ]

    _append_field(lines, "艺术家", _get_text(song, "artist"))
    _append_field(lines, "分类", _get_text(song, "category"))
    _append_field(lines, "BPM", _format_bpm(getattr(song, "bpm", "")))
    _append_field(lines, "版本", _get_text(song, "version"))
    _append_field(lines, "发布日期", _get_text(song, "release_date"))
    _append_field(lines, "备注", _get_text(song, "comment"))

    for sheet_type, sheets in (getattr(song, "difficulties", None) or {}).items():
        values = [_format_sheet_level(sheet) for sheet in sheets]
        values = [value for value in values if value]
        if values:
            lines.append(f"定数 ({_sheet_type_label(sheet_type)}): {' / '.join(values)}")

    return lines


async def load_song_jacket_bytes(
    game_code: str,
    result: SongQueryResult,
    *,
    arcade_sites: list[dict[str, Any]] | None = None,
) -> bytes | None:
    image_name = _get_text(result.song_data, "image_name")
    if not image_name:
        return None

    local_path = _local_jacket_path(game_code, image_name)
    if local_path is not None:
        if local_path.exists():
            try:
                return local_path.read_bytes()
            except OSError:
                return None
        return None

    url = image_name if _is_url(image_name) else _arcade_image_url(game_code, image_name, arcade_sites or [])
    if not url:
        return None

    try:
        return await http_client.get_bytes(url)
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[{game_code}] 曲绘下载失败，跳过: {url} ({e})")
        return None


def _arcade_image_url(game_code: str, image_name: str, sites: list[dict[str, Any]]) -> str:
    for site in sites:
        if not isinstance(site, dict) or site.get("gameCode") != game_code:
            continue
        base_url = str(site.get("dataSourceUrl") or "").rstrip("/")
        if not base_url:
            return ""
        image_path = f"img/cover/{image_name}" if _needs_cloudfront_cover_path(base_url, image_name) else image_name
        return urljoin(f"{base_url}/", image_path.lstrip("/"))
    return ""


def _needs_cloudfront_cover_path(base_url: str, image_name: str) -> bool:
    parsed = urlparse(base_url)
    host = parsed.hostname or ""
    return (host == "cloudfront.net" or host.endswith(".cloudfront.net")) and "/" not in image_name


def _local_jacket_path(game_code: str, image_name: str) -> Path | None:
    if _is_url(image_name):
        return None
    if not image_name.startswith("jacket/"):
        return None
    root = Path.cwd() / "data" / "chiffon_bot" / "template"
    if game_code == "maimai":
        return root / "maimai" / image_name
    if game_code == "chunithm":
        return root / "chunithm" / image_name
    return None


def _is_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _append_field(lines: list[str], label: str, value: str) -> None:
    if value:
        lines.append(f"{label}: {value}")


def _format_bpm(value: Any) -> str:
    if value in (None, ""):
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    return str(int(number)) if number.is_integer() else str(number)


def _format_sheet_level(sheet: Any) -> str:
    for attr in ("internal_level_value_new", "internal_level_value", "level_value"):
        value = getattr(sheet, attr, None)
        if value is not None:
            return f"{float(value):.1f}"
    return _get_text(sheet, "level")


def _get_text(obj: Any, attr: str) -> str:
    return str(getattr(obj, attr, "") or "").strip()


def _sheet_type_label(sheet_type: str) -> str:
    value = str(sheet_type or "standard").strip()
    return {"dx": "DX", "standard": "STANDARD"}.get(value.lower(), value.upper())


__all__ = ["format_song_text_detail", "load_song_jacket_bytes"]
