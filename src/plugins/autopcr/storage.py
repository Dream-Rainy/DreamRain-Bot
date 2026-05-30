from __future__ import annotations

from pathlib import Path

from nonebot import require

require("nonebot_plugin_localstore")

from nonebot_plugin_localstore import get_cache_dir, get_data_dir  # noqa: E402

PLUGIN_NAME = "autopcr"

PLUGIN_DATA_DIR = get_data_dir(PLUGIN_NAME)
PLUGIN_CACHE_DIR = get_cache_dir(PLUGIN_NAME)
EXCEL_CACHE_DIR = PLUGIN_CACHE_DIR / "excel"
REMOTE_FILE_CACHE_DIR = PLUGIN_CACHE_DIR / "remote_files"


def ensure_autopcr_storage() -> None:
    """Create adapter-owned localstore directories.

    The actual autopcr runtime data lives in the remote autopcr service. These
    directories are only for temporary files handled by the NoneBot adapter.
    """

    for path in (PLUGIN_DATA_DIR, PLUGIN_CACHE_DIR, EXCEL_CACHE_DIR, REMOTE_FILE_CACHE_DIR):
        path.mkdir(parents=True, exist_ok=True)
