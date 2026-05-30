"""公主连结角色模块 - NoneBot 版"""

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

import httpx
import pygtrie
from PIL import Image, ImageDraw
from rapidfuzz import process, fuzz

from nonebot import logger

from . import _pcr_data
from .compat.util import normalize_str, pic2b64
from .pcr_data_runtime import apply_pcr_data_override
from .storage import ICON_CACHE_DIR, ICON_WARMUP_STATE_FILE

UNKNOWN = 1000
ICON_BASE_URL = "https://redive.estertion.win/icon/unit"
ICON_CACHE_DIR.mkdir(parents=True, exist_ok=True)
ICON_WARMUP_STATE_PATH = ICON_WARMUP_STATE_FILE
ICON_WARMUP_VERSION = 1


@dataclass
class ImageResource:
    """图标资源，提供 open() 与 cqcode 兼容"""

    path: Path

    def open(self) -> Image.Image:
        img = Image.open(self.path)
        if self.path.suffix.lower() == ".webp":
            img = img.convert("RGBA")
        return img

    @property
    def cqcode(self):
        from .compat.util import pic2b64
        return f"[CQ:image,file={pic2b64(self.open())}]"


def _placeholder_icon(size: int = 64) -> Image.Image:
    image = Image.new("RGBA", (size, size), (235, 235, 235, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, size - 1, size - 1), outline=(180, 180, 180), width=2)
    draw.text((size // 3, size // 4), "?", fill=(90, 90, 90))
    return image


async def _download_icon(id_: int, star: int) -> Path | None:
    path = ICON_CACHE_DIR / f"{id_}{star}1.webp"
    if path.exists():
        return path
    url = f"{ICON_BASE_URL}/{id_}{star}1.webp"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            rsp = await client.get(url)
        if rsp.status_code != 200:
            logger.error(f"Failed to download {url}. HTTP {rsp.status_code}")
            return None
        path.write_bytes(rsp.content)
        return path
    except Exception as e:
        logger.error(f"Failed to download {url}: {e}")
        return None


def _load_warmup_state() -> dict:
    if not ICON_WARMUP_STATE_PATH.exists():
        return {}
    try:
        return json.loads(ICON_WARMUP_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_warmup_state(state: dict) -> None:
    ICON_WARMUP_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    ICON_WARMUP_STATE_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def get_icon_warmup_state() -> dict:
    return _load_warmup_state()


async def warmup_icons(
    force: bool = False,
    stars: tuple[int, ...] = (1, 3, 6),
    concurrency: int = 16,
    rebuild_arena_dic: bool = True,
) -> dict:
    stars = tuple(sorted(set(stars)))
    unit_ids = sorted(
        [
            int(uid)
            for uid in _pcr_data.CHARA_NAME.keys()
            if isinstance(uid, int) and 1000 < int(uid) < 1900
        ]
    )
    state = _load_warmup_state()
    total_units = len(unit_ids)
    expected_attempts = total_units * len(stars)

    if (
        not force
        and state.get("completed")
        and state.get("version") == ICON_WARMUP_VERSION
        and state.get("unit_count") == total_units
        and state.get("stars") == list(stars)
    ):
        return {
            "skipped": True,
            "message": "icon warmup already completed",
            "state": state,
        }

    semaphore = asyncio.Semaphore(max(1, int(concurrency)))
    success = 0
    failed = 0

    async def _worker(uid: int, star: int) -> None:
        nonlocal success, failed
        async with semaphore:
            result = await _download_icon(uid, star)
            if result:
                success += 1
            else:
                failed += 1

    tasks = [_worker(uid, star) for uid in unit_ids for star in stars]
    await asyncio.gather(*tasks)

    arena_msg = ""
    if rebuild_arena_dic:
        try:
            from .arena.record import update_dic

            arena_msg = update_dic()
        except Exception as e:
            arena_msg = f"update_dic failed: {e}"
            logger.error(arena_msg)

    new_state = {
        "completed": True,
        "version": ICON_WARMUP_VERSION,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "unit_count": total_units,
        "stars": list(stars),
        "attempted": expected_attempts,
        "success_count": success,
        "fail_count": failed,
        "arena_rebuild_message": arena_msg,
    }
    _save_warmup_state(new_state)
    logger.info(
        f"Icon warmup finished: success={success}, failed={failed}, total={expected_attempts}"
    )
    return {"skipped": False, "state": new_state}


class Roster:
    def __init__(self):
        self._roster = pygtrie.CharTrie()
        self._all_names: list[str] = []
        self._build()

    def _build(self):
        self._roster.clear()
        self._all_names = []
        for idx, names in _pcr_data.CHARA_NAME.items():
            for n in names:
                norm = normalize_str(n)
                if norm and norm not in self._roster:
                    self._roster[norm] = idx
                    self._all_names.append(norm)

    def update(self):
        import importlib
        if not apply_pcr_data_override():
            importlib.reload(_pcr_data)
            apply_pcr_data_override()
        self._build()
        return {"success": len(self._all_names), "duplicate": 0}

    def get_id(self, name: str) -> int:
        norm = normalize_str(name)
        val = self._roster.get(norm)
        return val if isinstance(val, int) else UNKNOWN

    def guess_id(self, name: str):
        """@return: id, name, score"""
        if not self._all_names:
            return UNKNOWN, "未知角色", 0
        result = process.extractOne(
            normalize_str(name),
            self._all_names,
            scorer=fuzz.WRatio,
        )
        if result is None:
            return UNKNOWN, "未知角色", 0
        matched, score, _ = result
        return self._roster[matched], matched, int(score)

    def parse_team(self, namestr: str):
        """@return: List[ids], unknown_namestr"""
        namestr = normalize_str(namestr.strip())
        team = []
        unknown = []
        while namestr:
            item = self._roster.longest_prefix(namestr)
            if not item:
                unknown.append(namestr[0])
                namestr = namestr[1:].lstrip()
            else:
                team.append(item.value)
                namestr = namestr[len(item.key) :].lstrip()
        return team, "".join(unknown)


roster = Roster()


def name2id(name: str) -> int:
    return roster.get_id(name)


def fromid(id_: int, star: int = 0, equip: int = 0) -> "Chara":
    return Chara(id_, star, equip)


def fromname(name: str, star: int = 0, equip: int = 0) -> "Chara":
    return Chara(name2id(name), star, equip)


def guess_id(name: str):
    return roster.guess_id(name)


def is_npc(id_: int) -> bool:
    if id_ in _pcr_data.UnavailableChara:
        return True
    return not (1000 < id_ < 1900)


async def download_chara_icon(id_: int, star: int) -> int:
    """下载角色头像，返回 0 成功，1 失败"""
    result = await _download_icon(id_, star)
    return 0 if result else 1


async def gen_team_pic(team: list["Chara"], size: int = 64, star_slot_verbose: bool = True) -> Image.Image:
    des = Image.new("RGBA", (len(team) * size, size), (255, 255, 255, 255))
    for i, c in enumerate(team):
        src = await c.render_icon(size, star_slot_verbose)
        des.paste(src, (i * size, 0), src)
    return des


class Chara:
    def __init__(self, id_: int, star: int = 0, equip: int = 0):
        self.id = id_
        self.star = star
        self.equip = equip

    @property
    def name(self) -> str:
        return _pcr_data.CHARA_NAME.get(self.id, _pcr_data.CHARA_NAME[UNKNOWN])[0]

    @property
    def is_npc(self) -> bool:
        return is_npc(self.id)

    async def get_icon(self, star: int = 0) -> ImageResource:
        star = star or self.star
        star = 1 if 1 <= star < 3 else 3 if 3 <= star < 6 else 6
        for candidate in (star, 3, 1, 6):
            path = await _download_icon(self.id, candidate)
            if path:
                return ImageResource(path)
        fallback = ICON_CACHE_DIR / "unknown.png"
        if not fallback.exists():
            _placeholder_icon().save(fallback)
        return ImageResource(fallback)

    async def get_icon_cqcode(self, star: int = 0):
        from nonebot.adapters.onebot.v11 import MessageSegment
        res = await self.get_icon(star)
        img = res.open()
        return MessageSegment.image(pic2b64(img))

    async def render_icon(self, size: int, star_slot_verbose: bool = True) -> Image.Image:
        """渲染带星级槽的图标（无 gadget 图时仅缩放）"""
        res = await self.get_icon(self.star)
        pic = res.open().convert("RGBA").resize((size, size), Image.Resampling.LANCZOS)
        return pic
