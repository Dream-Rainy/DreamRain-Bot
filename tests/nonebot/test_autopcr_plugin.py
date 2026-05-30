from __future__ import annotations

import nonebot
import pytest
from nonebot.plugin import get_plugin


def _load_autopcr():
    plugin = get_plugin("autopcr")
    if plugin is None:
        plugin = nonebot.load_plugin("src.plugins.autopcr")
    assert plugin is not None
    return plugin


async def test_autopcr_plugin_imports_with_nonebot(app):
    _load_autopcr()

    from src.plugins.autopcr import handlers

    assert handlers.prefix == "#"
    assert handlers._match_route("#配置日常")[0].func.__name__ == "config_clear_daily"
    assert handlers._match_route("#查装备 10 fav")[0].func.__name__ == "tool_used"
    assert "查装备" in handlers.tool_info


async def test_autopcr_storage_redirects_to_localstore(app):
    _load_autopcr()

    from src.submodule.autopcr.autopcr import constants

    assert "autopcr" in constants.CACHE_DIR
    assert "autopcr" in constants.CONFIG_PATH
    assert "src" not in constants.CACHE_DIR.replace("\\", "/")


@pytest.mark.parametrize(
    ("tokens", "expected"),
    [
        (["10", "fav"], {"start_rank": 10, "like_unit_only": True}),
        (["fav"], {"start_rank": None, "like_unit_only": True}),
    ],
)
async def test_autopcr_find_equip_parser(app, tokens, expected):
    _load_autopcr()

    from src.plugins.autopcr import handlers

    class FakeBotEvent:
        def __init__(self, message):
            self._message = message

        async def message(self):
            return self._message

    result = await handlers.tool_info["查装备"].config_parser(FakeBotEvent(tokens.copy()))

    assert result == expected


async def test_autopcr_recover_text_by_tokens(app):
    _load_autopcr()

    from src.plugins.autopcr.handlers import recover_text_by_tokens

    raw = "1 1 队伍1 春妈 蝶妈 END"
    assert recover_text_by_tokens(raw, ["队伍1", "春妈", "蝶妈", "END"]) == "队伍1 春妈 蝶妈 END"
