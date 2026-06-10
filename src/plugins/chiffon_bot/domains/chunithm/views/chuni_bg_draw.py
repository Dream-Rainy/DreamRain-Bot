import os
import tempfile
from pathlib import Path
from typing import Any

import diskcache
from nonebot import logger

from ....infra.html_render import template_to_pic

_CHIFFON_BOT_ROOT = Path(__file__).resolve().parents[3]  # views → chunithm → domains → chiffon_bot

_cache_dir = Path(tempfile.gettempdir()) / "dreamrain_bot" / "chuni_song_info_imgs"
_cache_dir.mkdir(parents=True, exist_ok=True)
_chuni_song_info_img_cache = diskcache.Cache(str(_cache_dir))

# HTML 模板（Jinja2 搜索路径，HTML 文件在 src/ 中，受 git 追踪）
_MAIMAI_HTML_TEMPLATE_DIR = str(_CHIFFON_BOT_ROOT / "domains/maimai/template")
_SHARED_RENDER_TEMPLATES = str(_CHIFFON_BOT_ROOT / "shared/render_templates")
_CHUNI_HTML_TEMPLATE_DIR = str(_CHIFFON_BOT_ROOT / "domains/chunithm/template")
_template_search_paths = (
    _MAIMAI_HTML_TEMPLATE_DIR,
    _SHARED_RENDER_TEMPLATES,
    _CHUNI_HTML_TEMPLATE_DIR,
)

# 素材/外部数据（data/ 目录，不在 git 中）
_DATA_DIR = Path(os.getcwd()) / "data" / "chiffon_bot"
_CHUNI_ASSETS_DIR = _DATA_DIR / "template" / "chunithm"
_CHUNI_ASSETS_DIR.mkdir(parents=True, exist_ok=True)
_template_base_uri = _CHUNI_ASSETS_DIR.resolve().as_uri()

# 字体目录（file:// URI，供模板中 @font-face 引用）
_FONTS_DIR_URI = (
    (_CHIFFON_BOT_ROOT / "shared" / "render_templates" / "fonts").resolve().as_uri()
)

_CHUNI_DEFAULT_BG_PAGE = "bg_html/X-VERSE-X/X-VERSE-X.html"


def _chart_to_template_data(chart: Any) -> dict[str, Any]:
    if hasattr(chart, "model_dump"):
        return chart.model_dump(mode="json", by_alias=True, exclude_none=True)
    if isinstance(chart, dict):
        return chart
    return {}


async def render_chuni_song_info_img(song_data) -> bytes:
    """渲染 CHUNITHM 乐曲信息图（与 ``chuni_song_info.html`` 模板配套）。"""
    song_id = int(song_data.id if hasattr(song_data, "id") else song_data["id"])
    cache_key = f"chuni_song_v2_{song_id}"
    cached_img = _chuni_song_info_img_cache.get(cache_key, default=None)
    if cached_img is not None and isinstance(cached_img, bytes):
        return cached_img

    template_name = "chuni_song_info.html"
    width = 1100
    height = 800

    difficulties = (song_data.difficulties if hasattr(song_data, "difficulties") else song_data.get("difficulties")) or {}
    standard_charts = [
        _chart_to_template_data(s)
        for s in (difficulties.get("standard") or difficulties.get("std") or [])
    ]
    ultima_charts = [
        _chart_to_template_data(s)
        for s in (difficulties.get("ultima") or [])
    ]
    standard_charts.extend(ultima_charts)
    # World's End 谱面（type="we"），arcade-songs 使用该 key
    we_charts = [
        _chart_to_template_data(s)
        for s in (difficulties.get("we") or [])
    ]

    n_std = len(standard_charts)
    if n_std > 5:
        height += (n_std - 5) * 56
    if we_charts:
        # WE 区块标题行 + 每行约 56px
        height += 60 + len(we_charts) * 56

    if hasattr(song_data, "model_dump"):
        song_info = {k: v for k, v in song_data.model_dump().items() if k != "difficulties"}
    else:
        song_info = {k: v for k, v in song_data.items() if k != "difficulties"}

    templates: dict[str, Any] = {
        "base_url": str(_CHUNI_ASSETS_DIR),
        "fonts_dir": _FONTS_DIR_URI,
        "bg_page_url": _CHUNI_DEFAULT_BG_PAGE,
        "bg_image_url": None,
        "song_info": song_info,
        "standard_charts": standard_charts,
        "we_charts": we_charts,
    }

    img_bytes = await template_to_pic(
        debug=False,
        template_path=_template_search_paths,
        template_name=template_name,
        templates=templates,
        device_scale_factor=1,
        pages={
            "viewport": {"width": width, "height": height},
            "base_url": _template_base_uri,
        },
    )
    _chuni_song_info_img_cache.set(cache_key, img_bytes, expire=None)
    return img_bytes


def clear_chuni_song_info_img_cache() -> None:
    """清除 CHUNITHM 歌曲信息图片缓存。"""
    _chuni_song_info_img_cache.clear()
