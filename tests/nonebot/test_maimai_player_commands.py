from __future__ import annotations

import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from tests.nonebot.test_arcade_queries import _dispatch, _find_matcher, _finish_capture
from tests.unit.test_maimai_player_handlers import _player


@pytest.mark.parametrize("failed", [False, True])
async def test_b50_matcher_sends_sdk_card_or_query_error(app, loaded_chiffon_bot, monkeypatch, failed):
    from src.plugins.chiffon_bot.app.commands import maimai

    domain = importlib.import_module("src.plugins.chiffon_bot.domains.maimai.handlers.b50")
    player = _player()
    if failed:
        player.bests.side_effect = TimeoutError("request timed out")
    monkeypatch.setattr(maimai.lxns_client.data.users, "ensure_lxns_bound_by_qq_lookup",
                        AsyncMock(return_value=SimpleNamespace(status="already_bound")))
    monkeypatch.setattr(type(maimai.lxns_client.data.players.maimai), "default_player", AsyncMock(return_value=player))
    monkeypatch.setattr(maimai, "ack_message", AsyncMock())
    monkeypatch.setattr(domain, "enhance_scores", AsyncMock(side_effect=lambda scores: scores))
    render = AsyncMock(return_value=b"b50-card")
    monkeypatch.setattr(domain.mai_bg_draw, "render_b50_img", render)
    responses = []
    _finish_capture(monkeypatch, maimai, responses)

    await _dispatch(app, "/mai.b50", 42, _find_matcher(maimai, "handle_b50"))

    assert len(responses) == 1
    assert responses[0].reply_to == 42
    if failed:
        assert "查询失败" in responses[0].text
        assert responses[0].image is None
        render.assert_not_awaited()
    else:
        assert responses[0].image == b"b50-card"
        assert render.await_args.kwargs["b35_data"][0]["id"] == 1
