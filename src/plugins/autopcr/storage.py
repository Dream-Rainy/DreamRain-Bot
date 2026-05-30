from __future__ import annotations

import shutil
from pathlib import Path

from nonebot import require

require("nonebot_plugin_localstore")

from nonebot_plugin_localstore import get_cache_dir, get_data_dir  # noqa: E402

from .compat import get_upstream_root, install_distutils_shim, upstream_import

PLUGIN_NAME = "autopcr"

PLUGIN_DATA_DIR = get_data_dir(PLUGIN_NAME)
PLUGIN_CACHE_DIR = get_cache_dir(PLUGIN_NAME)
STATIC_DATA_DIR = PLUGIN_DATA_DIR / "static"
RESULT_DIR = PLUGIN_DATA_DIR / "result"
CONFIG_DIR = PLUGIN_DATA_DIR / "http_server"
EXCEL_CACHE_DIR = PLUGIN_CACHE_DIR / "excel"
LOG_DIR = PLUGIN_CACHE_DIR / "log"


def _as_dir(path: Path) -> str:
    return str(path) + "/"


def _copy_static_data() -> None:
    source = get_upstream_root().parent / "data"
    if not source.exists():
        STATIC_DATA_DIR.mkdir(parents=True, exist_ok=True)
        return

    STATIC_DATA_DIR.mkdir(parents=True, exist_ok=True)
    for item in source.iterdir():
        target = STATIC_DATA_DIR / item.name
        if item.is_dir():
            if not target.exists():
                shutil.copytree(item, target)
        elif not target.exists():
            shutil.copy2(item, target)


def configure_autopcr_storage() -> None:
    """Redirect autopcr runtime files to nonebot-plugin-localstore."""

    install_distutils_shim()
    for path in (PLUGIN_DATA_DIR, PLUGIN_CACHE_DIR, STATIC_DATA_DIR, RESULT_DIR, CONFIG_DIR, EXCEL_CACHE_DIR, LOG_DIR):
        path.mkdir(parents=True, exist_ok=True)
    _copy_static_data()

    constants = upstream_import("constants")

    legacy_root = Path(constants.ROOT_DIR)
    constants.ROOT_DIR = _as_dir(PLUGIN_DATA_DIR)
    constants.CACHE_DIR = _as_dir(PLUGIN_CACHE_DIR)
    constants.RESULT_DIR = _as_dir(RESULT_DIR)
    constants.DATA_DIR = _as_dir(STATIC_DATA_DIR)
    constants.CONFIG_PATH = _as_dir(CONFIG_DIR)
    constants.OLD_CONFIG_PATH = str(legacy_root / "autopcr" / "http_server" / "config")
    constants.CLAN_BATTLE_FORBID_PATH = str(CONFIG_DIR / "clan_battle_forbidden.txt")
    constants.LOG_PATH = _as_dir(LOG_DIR)
    constants.refresh_headers()
