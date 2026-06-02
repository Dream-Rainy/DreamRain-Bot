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


async def test_autopcr_remote_structured_payload(app):
    _load_autopcr()

    from src.plugins.autopcr.remote import _messages_from_payload

    messages = _messages_from_payload(
        {
            "messages": [
                {"type": "lines", "lines": ["定时日志", "成功"]},
                {"type": "table", "header": ["时间", "数量"], "rows": [["05:00", 2]]},
            ],
        }
    )

    assert [message.kind for message in messages] == ["lines", "table"]
    assert messages[0].lines == ["定时日志", "成功"]
    assert messages[1].header == ["时间", "数量"]
    assert messages[1].rows == [["05:00", "2"]]


async def test_autopcr_remote_result_payloads(app):
    _load_autopcr()

    from src.plugins.autopcr.remote import _messages_from_payload

    messages = _messages_from_payload(
        {
            "messages": [
                {"type": "autopcr_task_result", "result": {"order": [], "result": {}}},
                {
                    "type": "autopcr_module_result",
                    "result": {"name": "查装备", "config": "", "log": "ok", "status": "成功", "table": {"header": [], "data": []}},
                },
            ],
        }
    )

    assert [message.kind for message in messages] == ["autopcr_task_result", "autopcr_module_result"]
    assert messages[0].result == {"order": [], "result": {}}
    assert messages[1].result["name"] == "查装备"


async def test_autopcr_remote_structured_rendering(app):
    _load_autopcr()

    from src.plugins.autopcr.handlers import _render_remote_message
    from src.plugins.autopcr.remote import RemoteMessage

    lines = _render_remote_message(RemoteMessage(kind="lines", lines=["今日定时任务：启动1个，完成1个"]))
    table = _render_remote_message(
        RemoteMessage(kind="table", header=["时间", "定时任务数"], rows=[["05:00", "3"]])
    )

    assert lines.startswith(b"\x89PNG")
    assert table.startswith(b"\x89PNG")


async def test_autopcr_remote_result_rendering(app):
    _load_autopcr()

    from src.plugins.autopcr.handlers import _render_remote_message
    from src.plugins.autopcr.remote import RemoteMessage

    task_result = {
        "order": ["a"],
        "result": {
            "a": {
                "name": "清体力",
                "config": "默认",
                "log": "完成",
                "status": "成功",
                "table": {"header": [], "data": []},
            }
        },
    }
    module_result = {
        "name": "查box",
        "config": "",
        "log": "",
        "status": "成功",
        "table": {
            "header": ["名字", {"角色A": ["星级", "等级"]}],
            "data": [{"名字": "tester", "角色A": {"星级": 5, "等级": 310}}],
        },
    }

    task = _render_remote_message(RemoteMessage(kind="autopcr_task_result", result=task_result))
    module = _render_remote_message(RemoteMessage(kind="autopcr_module_result", result=module_result))

    assert task.startswith(b"\x89PNG")
    assert module.startswith(b"\x89PNG")


async def test_autopcr_context_can_include_visible_user_ids(app, monkeypatch):
    _load_autopcr()

    from src.plugins.autopcr import handlers

    monkeypatch.setattr(handlers, "ACTIVE_GROUPS", {"100", "not-a-group"})

    class FakeBotEvent:
        async def group_id(self):
            return "200"

        async def send_qq(self):
            return "123"

        async def is_admin(self):
            return True

        async def is_super_admin(self):
            return False

        async def call_action(self, action, **params):
            assert action == "get_group_member_list"
            if params["group_id"] == 100:
                return [{"user_id": 111}, {"user_id": "222"}]
            if params["group_id"] == 200:
                return [{"user_id": "222"}, {"user_id": 333}]
            raise AssertionError(params)

    context = await handlers._context(FakeBotEvent(), include_visible_user_ids=True)

    assert context["sender_qq"] == "123"
    assert context["group_id"] == "200"
    assert context["visible_user_ids"] == ["111", "222", "333"]


async def test_autopcr_remote_binary_image_response(app):
    _load_autopcr()

    import httpx

    from src.plugins.autopcr.remote import AutopcrRemoteClient

    client = object.__new__(AutopcrRemoteClient)
    result = await client._result_from_response(
        httpx.Response(200, headers={"content-type": "image/webp"}, content=b"webp-bytes")
    )

    assert len(result.messages) == 1
    assert result.messages[0].kind == "image"
    assert result.messages[0].mime_type == "image/webp"
    assert result.messages[0].content == b"webp-bytes"
