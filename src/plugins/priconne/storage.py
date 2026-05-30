from __future__ import annotations

import shutil
from pathlib import Path

from nonebot import logger, require

require("nonebot_plugin_localstore")
from nonebot_plugin_localstore import get_cache_dir, get_data_dir

PLUGIN_NAME = "priconne"
PLUGIN_ROOT = Path(__file__).resolve().parent

PRICONNE_DATA_DIR = get_data_dir(PLUGIN_NAME)
PRICONNE_CACHE_DIR = get_cache_dir(PLUGIN_NAME)

ACCOUNT_DIR = PRICONNE_DATA_DIR / "account"
CLANBATTLE_DATA_DIR = PRICONNE_DATA_DIR / "clanbattle"
FENDAO_DATA_DIR = PRICONNE_DATA_DIR / "fendao"
SUPPORT_QUERY_DATA_DIR = PRICONNE_DATA_DIR / "support_query"
DEVICE_FILE = PRICONNE_DATA_DIR / "device.json"
VERSION_FILE = PRICONNE_DATA_DIR / "version.txt"
RUNGROUP_FILE = PRICONNE_DATA_DIR / "clanbattle" / "rungroup.json"
PCR_DATA_FILE = PRICONNE_DATA_DIR / "_pcr_data.py"

ICON_CACHE_DIR = PRICONNE_CACHE_DIR / "icons"
ICON_WARMUP_STATE_FILE = PRICONNE_CACHE_DIR / "icon_warmup_state.json"
ARENA_CACHE_DIR = PRICONNE_CACHE_DIR / "arena"
ARENA_BUFFER_DIR = ARENA_CACHE_DIR / "buffer"
ARENA_BUFFER_INDEX_FILE = ARENA_BUFFER_DIR / "buffer.json"
ARENA_DIC_FILE = ARENA_CACHE_DIR / "dic.npy"
ARENA_BEST_ATK_RECORDS_FILE = ARENA_BUFFER_DIR / "best_atk_records.json"
CLANBATTLEWORK_FILE = PRICONNE_CACHE_DIR / "fendao" / "clanbattlework.json"

STATIC_IMG_DIR = PLUGIN_ROOT / "img"
STATIC_FONT_DIR = PLUGIN_ROOT / "fonts"
STATIC_DEVICE_FILE = PLUGIN_ROOT / "device.json"
STATIC_VERSION_ORIGIN_FILE = PLUGIN_ROOT / "version.origin.txt"
STATIC_CLANBATTLEWORK_LOCAL_FILE = PLUGIN_ROOT / "fendao" / "clanbattlework.local.json"


def _copy_file_missing(src: Path, dst: Path) -> None:
    if not src.exists() or dst.exists():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def _copy_tree_missing(src: Path, dst: Path, *, ignore_names: set[str] | None = None) -> None:
    if not src.exists():
        return
    ignore_names = ignore_names or set()
    for item in src.iterdir():
        if item.name in ignore_names:
            continue
        target = dst / item.name
        if item.is_dir():
            _copy_tree_missing(item, target)
        elif not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)


def _ensure_dirs() -> None:
    for directory in (
        PRICONNE_DATA_DIR,
        PRICONNE_CACHE_DIR,
        ACCOUNT_DIR,
        CLANBATTLE_DATA_DIR,
        FENDAO_DATA_DIR,
        SUPPORT_QUERY_DATA_DIR,
        ICON_CACHE_DIR,
        ARENA_BUFFER_DIR,
        CLANBATTLEWORK_FILE.parent,
    ):
        directory.mkdir(parents=True, exist_ok=True)


def migrate_legacy_storage() -> None:
    old_data_dir = PLUGIN_ROOT / "data"
    old_arena_dir = PLUGIN_ROOT / "arena"
    old_arena_buffer_dir = old_arena_dir / "buffer"
    old_fendao_dir = PLUGIN_ROOT / "fendao"
    old_clanbattle_dir = PLUGIN_ROOT / "clanbattle"

    try:
        _ensure_dirs()
        _copy_tree_missing(
            old_data_dir,
            PRICONNE_DATA_DIR,
            ignore_names={"icons", "icon_warmup_state.json"},
        )
        _copy_file_missing(STATIC_DEVICE_FILE, DEVICE_FILE)
        _copy_file_missing(PLUGIN_ROOT / "version.txt", VERSION_FILE)
        _copy_file_missing(old_clanbattle_dir / "rungroup.json", RUNGROUP_FILE)

        _copy_tree_missing(old_data_dir / "icons", ICON_CACHE_DIR)
        _copy_file_missing(old_data_dir / "icon_warmup_state.json", ICON_WARMUP_STATE_FILE)
        _copy_tree_missing(old_arena_buffer_dir, ARENA_BUFFER_DIR)
        _copy_file_missing(old_arena_dir / "dic.npy", ARENA_DIC_FILE)
        _copy_file_missing(old_fendao_dir / "clanbattlework.json", CLANBATTLEWORK_FILE)

        if not ARENA_BUFFER_INDEX_FILE.exists():
            ARENA_BUFFER_INDEX_FILE.write_text("{}", encoding="utf-8")
    except Exception as e:
        logger.warning(f"priconne legacy storage migration failed: {e}")


migrate_legacy_storage()
