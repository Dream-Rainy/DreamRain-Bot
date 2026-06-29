from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

import nonebot
import pytest
import pytest_asyncio
from nonebug import NONEBOT_INIT_KWARGS
from nonebot.plugin import get_plugin
from tortoise import Tortoise

from arcade_helper.storage.tortoise import MODEL_MODULE as ARCADE_HELPER_MODEL_MODULE
from tests.fixtures.song_seed import seed_song_data


BOT_MODEL_MODULE = "src.plugins.chiffon_bot.infra.db.models"


def _drop_imported_module_tree(module_name: str) -> None:
    for name in list(sys.modules):
        if name == module_name or name.startswith(f"{module_name}."):
            del sys.modules[name]


def load_nonebot_plugin(module_name: str, plugin_name: str):
    plugin = get_plugin(plugin_name)
    if plugin is not None:
        return plugin

    _drop_imported_module_tree(module_name)
    plugin = nonebot.load_plugin(module_name)
    assert plugin is not None
    return plugin


def load_saa_plugin():
    return load_nonebot_plugin("nonebot_plugin_saa", "nonebot_plugin_saa")


def load_chiffon_bot_plugin():
    load_saa_plugin()
    return load_nonebot_plugin("src.plugins.chiffon_bot", "chiffon_bot")


def pytest_configure(config: pytest.Config) -> None:
    config.stash[NONEBOT_INIT_KWARGS] = {
        "driver": "~fastapi",
        "command_start": ["/"],
        "host": "127.0.0.1",
        "port": 18080,
        "superusers": {"test_superuser"},
        "lxns_api_key": "test",
        "lxns_client_id": "test",
        "lxns_client_secret": "test",
        "db_engine": "sqlite",
        "db_url": "data/test.sqlite3",
        "permission_admin_path": "data/test-permissions.json",
    }


@pytest.fixture()
def loaded_chiffon_bot(app):
    return load_chiffon_bot_plugin()


@pytest_asyncio.fixture()
async def seeded_song_db(tmp_path: Path, loaded_chiffon_bot):
    db_path = tmp_path / "songs.sqlite3"
    await Tortoise.init(
        {
            "connections": {
                "default": {
                    "engine": "tortoise.backends.sqlite",
                    "credentials": {"file_path": str(db_path)},
                }
            },
            "apps": {
                "models": {
                    "models": [ARCADE_HELPER_MODEL_MODULE, BOT_MODEL_MODULE],
                    "default_connection": "default",
                }
            },
        }
    )
    await Tortoise.generate_schemas()
    await seed_song_data()
    try:
        yield
    finally:
        await Tortoise.close_connections()


@pytest.fixture()
def song_indexes(seeded_song_db):
    from src.plugins.chiffon_bot.integrations.lxns.plugin_data import plugin_data
    from tests.fixtures.song_seed import (
        CHUNI_SONG_ID,
        CHUNI_SONG_TITLE,
        MAI_SONG_ID,
        MAI_SONG_TITLE,
    )

    plugin_data.mai_song_index = {MAI_SONG_ID: MAI_SONG_TITLE}
    plugin_data.chuni_song_index = {CHUNI_SONG_ID: CHUNI_SONG_TITLE}
    plugin_data.mai_song_data = {}
    plugin_data.chuni_song_data = {}
    return plugin_data
