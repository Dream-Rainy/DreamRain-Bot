from __future__ import annotations

import nonebot
import pytest
import sys
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


async def test_autopcr_plugin_does_not_import_upstream_runtime(app):
    _load_autopcr()

    assert not any(name.startswith("_dreamrain_autopcr_upstream") for name in sys.modules)


def test_autopcr_public_base_accepts_login_url():
    from src.plugins.autopcr.config import Config

    config = Config(autopcr_public_base_url="https://autopcr.example.com/daily/login")

    assert config.autopcr_public_base_url == "https://autopcr.example.com/daily/"


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


async def test_autopcr_remote_result_payload(app):
    _load_autopcr()

    from src.plugins.autopcr.remote import _messages_from_payload

    messages = _messages_from_payload(
        {
            "messages": [
                {"type": "text", "text": "ok"},
                {"type": "image", "url": "https://example.com/result.webp"},
            ],
        }
    )

    assert [message.kind for message in messages] == ["text", "image"]
    assert messages[0].text == "ok"
    assert messages[1].url == "https://example.com/result.webp"
