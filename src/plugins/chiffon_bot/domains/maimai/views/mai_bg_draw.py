import bisect
import random
from pathlib import Path
from typing import Any
import tempfile
import diskcache
import hashlib
import json
import os

import aiohttp
from nonebot import logger

from ..schemas import MaiSongData

from ....infra.html_render import template_to_pic

_CHIFFON_BOT_ROOT = Path(__file__).resolve().parents[
    3
]  # .../chiffon_bot（views → maimai → domains → chiffon_bot）

# 歌曲信息图片磁盘缓存（使用系统临时目录）
_cache_dir = Path(tempfile.gettempdir()) / "dreamrain_bot" / "song_info_imgs"
_cache_dir.mkdir(parents=True, exist_ok=True)
_song_info_img_cache = diskcache.Cache(str(_cache_dir))

# B50图片磁盘缓存
_b50_cache_dir = Path(tempfile.gettempdir()) / "dreamrain_bot" / "b50_imgs"
_b50_cache_dir.mkdir(parents=True, exist_ok=True)
_b50_img_cache = diskcache.Cache(str(_b50_cache_dir))

# HTML 模板（Jinja2 搜索路径，HTML 文件在 src/ 中，受 git 追踪）
_MAIMAI_HTML_TEMPLATE_DIR = str(_CHIFFON_BOT_ROOT / "domains/maimai/template")
_SHARED_RENDER_TEMPLATES = str(_CHIFFON_BOT_ROOT / "shared/render_templates")
_CHUNI_HTML_TEMPLATE_DIR = str(_CHIFFON_BOT_ROOT / "domains/chunithm/template")
template_search_paths = (
    _MAIMAI_HTML_TEMPLATE_DIR,
    _SHARED_RENDER_TEMPLATES,
    _CHUNI_HTML_TEMPLATE_DIR,
)

# 素材/外部数据（data/ 目录，不在 git 中）
_DATA_DIR = Path(os.getcwd()) / "data" / "chiffon_bot"
_MAIMAI_ASSETS_DIR = _DATA_DIR / "template" / "maimai"
_MAIMAI_ASSETS_DIR.mkdir(parents=True, exist_ok=True)
_template_base_uri = _MAIMAI_ASSETS_DIR.resolve().as_uri()

# 字体目录（file:// URI，供模板中 @font-face 引用）
_FONTS_DIR_URI = (
    (_CHIFFON_BOT_ROOT / "shared" / "render_templates" / "fonts").resolve().as_uri()
)

# API 背景图缓存
_BG_API_CACHE_DIR = _DATA_DIR / "bg_api_cache"
_BG_API_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# 需从外部 API 获取背景的版本映射表
# key: song_version_formatted（已 lower().replace(" ", "_")，经过版本规范化之后的值）
# value: API 接受的 version 参数（真代|超代|檄代|橙代|晓代|桃代|樱代|紫代|堇代|白代|雪代|辉代|DX|DX2021|DX2022|Dx2023|DX2024|DX2025|DX2026|宴|XVERSE|XVERSEX）
_BGAPI_VERSION_MAP: dict[str, str] = {
    # 示例（由用户手动填写）：
    # "prism_plus": "DX2026",
    # "宴": "宴",
	"maimai": "maimai",
	"maimai PLUS": "maimai",
	"GreeN": "green",
	"GreeN PLUS": "greenplus",
	"ORANGE": "orange",
	"ORANGE PLUS": "orangeplus",
	"PiNK": "pink",
	"PiNK PLUS": "pinkplus",
	"MURASAKi": "murasaki",
	"MURASAKi PLUS": "murasakiplus",
	"MiLK": "milk",
	"MiLK PLUS": "milkplus"
}


async def _fetch_bgapi_image(api_version: str, width: int, height: int) -> str:
    """从 https://iiii.icu/MaiCodePicmaker/ 获取背景图，永久缓存为本地文件。

    Returns:
        file:/// URI，可直接用于模板中的 <img src>。
    """
    cache_path = _BG_API_CACHE_DIR / f"{api_version}_{width}x{height}.png"
    if cache_path.exists():
        return cache_path.as_uri()

    url = f"https://iiii.icu/MaiCodePicmaker/{api_version}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url, params={"Xsize": width, "Ysize": height}) as resp:
            resp.raise_for_status()
            data = await resp.read()

    cache_path.write_bytes(data)
    logger.info(f"BG API 背景已缓存: {cache_path.name}")
    return cache_path.as_uri()

dx_rating_UI = {
	0: "UI_CMN_DXRating_01.png",
	1000: "UI_CMN_DXRating_02.png",
	2000: "UI_CMN_DXRating_03.png",
	4000: "UI_CMN_DXRating_04.png",
	7000: "UI_CMN_DXRating_05.png",
	10000: "UI_CMN_DXRating_06.png",
	12000: "UI_CMN_DXRating_07.png",
	13000: "UI_CMN_DXRating_08.png",
	14000: "UI_CMN_DXRating_09.png",
	14500: "UI_CMN_DXRating_10.png",
	15000: "UI_CMN_DXRating_11.png",
}

gradients = {
	0: "linear-gradient(to left, transparent 10%, rgba(111, 225, 99, 0.4) 35%, rgba(111, 225, 99, 0.8) 50%, rgb(111, 225, 99) 60%)",
	1: "linear-gradient(to left, transparent 10%, rgba(255, 186, 1, 0.4) 35%, rgba(255, 186, 1, 0.8) 50%, rgb(255, 186, 1) 60%)",
	2: "linear-gradient(to left, transparent 10%, rgba(255, 123, 123, 0.4) 35%, rgba(255, 123, 123, 0.8) 50%, rgb(255, 123, 123) 60%)",
	3: "linear-gradient(to left, transparent 10%, rgba(159, 81, 220, 0.4) 35%, rgba(159, 81, 220, 0.8) 50%, rgb(159, 81, 220) 60%)",
	4: "linear-gradient(to left, transparent 10%, rgba(219, 170, 255, 0.4) 35%, rgba(219, 170, 255, 0.8) 50%, rgb(219, 170, 255) 60%)",
}

shadows = {
	0: "1px 1px 0 rgba(111, 225, 99, 1), -1px -1px 0 rgba(111, 225, 99, 1), 1px -1px 0 rgba(111, 225, 99, 1), -1px 1px 0 rgba(111, 225, 99, 1), 0 1px 0 rgba(111, 225, 99, 1), 0 -1px 0 rgba(111, 225, 99, 1), 1px 0 0 rgba(111, 225, 99, 1), -1px 0 0 rgba(111, 225, 99, 1)",
	1: "1px 1px 0 rgba(255, 186, 1, 1), -1px -1px 0 rgba(255, 186, 1, 1), 1px -1px 0 rgba(255, 186, 1, 1), -1px 1px 0 rgba(255, 186, 1, 1), 0 1px 0 rgba(255, 186, 1, 1), 0 -1px 0 rgba(255, 186, 1, 1), 1px 0 0 rgba(255, 186, 1, 1), -1px 0 0 rgba(255, 186, 1, 1)",
	2: "1px 1px 0 rgba(255, 123, 123, 1), -1px -1px 0 rgba(255, 123, 123, 1), 1px -1px 0 rgba(255, 123, 123, 1), -1px 1px 0 rgba(255, 123, 123, 1), 0 1px 0 rgba(255, 123, 123, 1), 0 -1px 0 rgba(255, 123, 123, 1), 1px 0 0 rgba(255, 123, 123, 1), -1px 0 0 rgba(255, 123, 123, 1)",
	3: "1px 1px 0 rgba(159, 81, 220, 1), -1px -1px 0 rgba(159, 81, 220, 1), 1px -1px 0 rgba(159, 81, 220, 1), -1px 1px 0 rgba(159, 81, 220, 1), 0 1px 0 rgba(159, 81, 220, 1), 0 -1px 0 rgba(159, 81, 220, 1), 1px 0 0 rgba(159, 81, 220, 1), -1px 0 0 rgba(159, 81, 220, 1)",
	4: "1px 1px 0 rgba(219, 170, 255, 1), -1px -1px 0 rgba(219, 170, 255, 1), 1px -1px 0 rgba(219, 170, 255, 1), -1px 1px 0 rgba(219, 170, 255, 1), 0 1px 0 rgba(219, 170, 255, 1), 0 -1px 0 rgba(219, 170, 255, 1), 1px 0 0 rgba(219, 170, 255, 1), -1px 0 0 rgba(219, 170, 255, 1)",
}


sorted_keys = sorted(dx_rating_UI.keys())


def get_rating_image(value: int) -> str:
	pos = bisect.bisect_right(sorted_keys, value) - 1
	nearest_key = sorted_keys[pos]
	return dx_rating_UI[nearest_key]


def _generate_cache_key(user_data: dict, b35_data: list, b15_data: list, r50_data: list, width: int, height: int) -> str:
	"""生成B50图片的缓存键（基于数据哈希）。"""
	# 构建用于哈希的数据结构
	cache_data = {
		"user_data": user_data,
		"b35_data": b35_data,
		"b15_data": b15_data,
		"r50_data": r50_data,
		"width": width,
		"height": height,
	}
	# 序列化为JSON字符串并计算哈希
	data_str = json.dumps(cache_data, sort_keys=True, ensure_ascii=False)
	hash_value = hashlib.sha256(data_str.encode('utf-8')).hexdigest()
	return f"b50_{hash_value}"


async def render_b50_img(
	user_data: dict,
	b35_data: list = [],
	b15_data: list = [],
	r50_data: list = [],
	width: int = 1280,
	height: int = 2280,
) -> bytes:
	# 检查磁盘缓存
	cache_key = _generate_cache_key(user_data, b35_data, b15_data, r50_data, width, height)
	cached_img = _b50_img_cache.get(cache_key, default=None)
	if cached_img is not None and isinstance(cached_img, bytes):
		return cached_img
	
	template_name = "b50.html"

	_b50_bg_page = "bg_html/prism_plus/prism_plus.html"

	templates = {
		"base_url": str(_MAIMAI_ASSETS_DIR),
		"fonts_dir": _FONTS_DIR_URI,
		"bg_page_url": _b50_bg_page,
		"bg_image_url": None,
		"title_img": "assets/title_bg_prism.png",
		"gradients": gradients,
		"shadows": shadows,
		"player_name": user_data["data"]["name"],
		"dx_rating": str(user_data["data"]["rating"]).zfill(5),
		"dx_rating_image": f"assets/{get_rating_image(user_data['data']['rating'])}",
		"player_info_bg": f"frame/UI_Frame_{str(user_data['data']['frame']['id']).zfill(6)}.png",
		"trophy_color": f"assets/UI_CMN_Shougou_{user_data['data']['trophy']['color']}.png",
		"trophy_name": user_data["data"]["trophy"]["name"],
		"player_panel": f"plate/UI_Plate_{str(user_data['data']['name_plate']['id']).zfill(6)}.png",
		"player_avatar": f"icon/UI_Icon_{str(user_data['data']['icon']['id']).zfill(6)}.png",
		"player_class": f"assets/UI_FBR_Class_{str(user_data['data']['class_rank']).zfill(2)}.png",
		"player_course": f"assets/UI_DNM_DaniPlate_{str(user_data['data']['course_rank']).zfill(2)}.png",
		"b35_data": b35_data,
		"b15_data": b15_data,
		"r50_data": r50_data,
		"trophy_scale": 1.2,
		"b50_scale": 0.30,
	}

	img_bytes = await template_to_pic(
		debug=False,
		template_path=template_search_paths,
		template_name=template_name,
		templates=templates,
		device_scale_factor=1,
		type="jpeg",
		quality=92,
		pages={
			"viewport": {"width": width, "height": height},
			"base_url": _template_base_uri,
		},
	)
	
	# 缓存生成的图片到磁盘
	cache_key = _generate_cache_key(user_data, b35_data, b15_data, r50_data, width, height)
	_b50_img_cache.set(cache_key, img_bytes, expire=None)
	
	return img_bytes


async def render_r50_img(user_data: dict, recent_data: list) -> bytes:
	return await render_b50_img(user_data=user_data, r50_data=recent_data, height=2200)


def clear_song_info_img_cache() -> None:
	"""清除歌曲信息图片缓存（磁盘缓存）。"""
	_song_info_img_cache.clear()


def clear_b50_img_cache() -> None:
	"""清除B50图片缓存（磁盘缓存）。"""
	_b50_img_cache.clear()


def clear_all_img_cache() -> None:
	"""清除所有图片缓存（歌曲信息和B50）。"""
	clear_song_info_img_cache()
	clear_b50_img_cache()


async def render_song_info_img(song_data: MaiSongData) -> bytes:
	"""渲染歌曲信息图片（带磁盘缓存）。
	
	Args:
		song_data: 歌曲数据
		
	Returns:
		图片字节数据
	"""
	# 检查磁盘缓存
	cache_key = f"song_{song_data.id}"
	cached_img = _song_info_img_cache.get(cache_key, default=None)
	if cached_img is not None and isinstance(cached_img, bytes):
		return cached_img
	
	template_name = "song_info.html"
	width = 1100
	height = 800

	song_data_standard = [
		sheet.model_dump(
			mode="json",
			by_alias=True,
			exclude_none=True,
		)
		for sheet in song_data.difficulties.get("standard", [])
	]

	song_data_dx = [
		sheet.model_dump(
			mode="json",
			by_alias=True,
			exclude_none=True,
		)
		for sheet in song_data.difficulties.get("dx", [])
	]
	song_data_utage = [
		sheet.model_dump(
			mode="json",
			by_alias=True,
			exclude_none=True,
		)
		for sheet in song_data.difficulties.get('utage', [])
	]

	song_info = song_data.model_dump(
		mode="json",
		by_alias=True,
		exclude={"difficulties", "collections"},
	)

	# 同时提取 dx 和 sd 的 regions 数据
	regions_dx = None
	regions_sd = None
	regions_utage = None
	
	if song_data_dx and len(song_data_dx) > 0 and "regions" in song_data_dx[0]:
		regions_dx = song_data_dx[0]["regions"]
	
	if song_data_standard and len(song_data_standard) > 0 and "regions" in song_data_standard[0]:
		regions_sd = song_data_standard[0]["regions"]
	
	if song_data_utage and len(song_data_utage) > 0 and "regions" in song_data_utage[0]:
		regions_utage = song_data_utage[0]["regions"]
	
	# 将 regions 数据添加到 song_info
	if regions_dx:
		song_info["regions_dx"] = regions_dx
	if regions_sd:
		song_info["regions_sd"] = regions_sd
	if regions_utage:
		song_info["regions_utage"] = regions_utage

	if song_data_dx != [] and song_data_standard != []:
		height = 1060
	
	if len(song_data_dx) > 4 or len(song_data_standard) > 4:
		height += 70
	
	if len(song_data_dx) + len(song_data_standard) >= 10:
		height += 70
	
	# if song_data_dx:
	# 	for chart in song_data_dx:
	# 		note_designer = chart.get("noteDesigner", "")
	# 		if note_designer and len(note_designer) >= 8:
	# 			height += 30
    
	# if song_data_standard:
	# 	for chart in song_data_standard:
	# 		note_designer = chart.get("noteDesigner", "")
	# 		if note_designer and len(note_designer) >= 8:
	# 			height += 30
    
	if song_data_utage:
		# for chart in song_data_utage:
		# 	note_designer = chart.get("noteDesigner", "")
		# 	if note_designer and len(note_designer) >= 8:
		# 		height += 30
			
			height += 30

	song_version = song_info.get("version", "prism_plus")

	if song_version in ['maimaiでらっくす', 'maimaiでらっくす PLUS']:
		song_version = song_version.replace("maimai", "")

	if song_version == 'FiNALE':
		# import random
		song_version = random.choice(['finale_1', 'finale_2'])


	# 若该版本在映射表中，则从外部 API 获取（并永久缓存）背景图
	song_version_formatted = song_version.lower().replace(" ", "_")
	bg_image_url: str | None = None
	if song_version in _BGAPI_VERSION_MAP:
		api_version = _BGAPI_VERSION_MAP[song_version]
		try:
			bg_image_url = await _fetch_bgapi_image(api_version, width, height)
		except Exception as e:
			logger.warning(f"BG API 背景获取失败，回退至本地模板: {e}")
			song_version_formatted = "prism_plus"
	
	if regions_utage:
		try:
			bg_image_url = await _fetch_bgapi_image("utg", width, height)
		except Exception as e:
			logger.warning(f"BG API 背景获取失败，回退至本地模板: {e}")
			song_version_formatted = "buddies"

	templates = {
		"base_url": str(_MAIMAI_ASSETS_DIR),
		"fonts_dir": _FONTS_DIR_URI,
		"bg_page_url": f"bg_html/{song_version_formatted}/{song_version_formatted}.html",
		"bg_image_url": bg_image_url,
		"song_info": song_info,
		"dx_charts": song_data_dx,
		"sd_charts": song_data_standard,
		'utage_charts': song_data_utage,
	}

	img_bytes = await template_to_pic(
		debug=False,
		template_path=template_search_paths,
		template_name=template_name,
		templates=templates,
		device_scale_factor=1,
		pages={
			"viewport": {"width": width, "height": height},
			"base_url": _template_base_uri,
		},
	)
	
	# 缓存生成的图片到磁盘
	cache_key = f"song_{song_data.id}"
	_song_info_img_cache.set(cache_key, img_bytes, expire=None)  # 永久缓存，直到手动清除
	
	return img_bytes



