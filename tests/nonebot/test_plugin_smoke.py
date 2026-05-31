from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

LOCAL_PLUGIN_DIRS = {
    path.name
    for path in (REPO_ROOT / "src" / "plugins").iterdir()
    if path.is_dir() and not path.name.startswith("_")
}

CORE_LOCAL_PLUGINS = {
    "autopcr",
    "chiffon_bot",
    "permission_admin",
    "priconne",
}

KNOWN_ORM_REVISIONS = {
    "e828532300c4",
}


def _run_clean_nonebot_script(script: str) -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = (
        str(REPO_ROOT)
        if not env.get("PYTHONPATH")
        else f"{REPO_ROOT}{os.pathsep}{env['PYTHONPATH']}"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_core_local_plugins_load_together_in_clean_process():
    script = f"""
import nonebot
from nonebot.adapters.onebot.v11 import Adapter as OnebotAdapter
from nonebot.plugin import get_loaded_plugins

nonebot.init(
    driver="~fastapi",
    command_start=["/"],
    host="127.0.0.1",
    port=18080,
    superusers={{"10000"}},
    lxns_api_key="test",
    lxns_client_id="test",
    lxns_client_secret="test",
    db_engine="sqlite",
    db_url="data/test.sqlite3",
    permission_admin_path="data/test-permissions.json",
)
nonebot.get_driver().register_adapter(OnebotAdapter)
nonebot.load_plugin("nonebot_plugin_saa")
nonebot.load_plugins("src/plugins")

loaded_names = {{plugin.name for plugin in get_loaded_plugins()}}
missing_local_plugins = {LOCAL_PLUGIN_DIRS!r} - loaded_names
missing_core_plugins = {CORE_LOCAL_PLUGINS!r} - loaded_names
assert not missing_local_plugins, f"missing local plugins: {{sorted(missing_local_plugins)}}"
assert not missing_core_plugins, f"missing core plugins: {{sorted(missing_core_plugins)}}"
"""
    _run_clean_nonebot_script(script)


def test_orm_can_resolve_known_migration_revisions_in_clean_process():
    script = f"""
import nonebot
from alembic.script import ScriptDirectory
from nonebot.adapters.onebot.v11 import Adapter as OnebotAdapter

nonebot.init(
    driver="~fastapi",
    command_start=["/"],
    host="127.0.0.1",
    port=18080,
    superusers={{"10000"}},
    lxns_api_key="test",
    lxns_client_id="test",
    lxns_client_secret="test",
    db_engine="sqlite",
    db_url="data/test.sqlite3",
    permission_admin_path="data/test-permissions.json",
)
nonebot.get_driver().register_adapter(OnebotAdapter)
nonebot.load_plugin("nonebot_plugin_saa")
nonebot.load_plugins("src/plugins")

import nonebot_plugin_orm as orm
from nonebot_plugin_orm.migrate import AlembicConfig

orm._init_orm()
with AlembicConfig() as alembic_config:
    script = ScriptDirectory.from_config(alembic_config)
    missing = {{
        revision
        for revision in {KNOWN_ORM_REVISIONS!r}
        if script.get_revision(revision) is None
    }}

assert not missing, f"missing revisions: {{sorted(missing)}}"
"""
    _run_clean_nonebot_script(script)
