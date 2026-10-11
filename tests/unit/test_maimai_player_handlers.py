from __future__ import annotations

import importlib
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from arcade_helper.core.result import DataFreshness, DataResult
from arcade_helper.players.maimai import (
    MaimaiBests, MaimaiProfile, MaimaiRecents, MaimaiScore, MaimaiTrend,
)


def _result(data):
    return DataResult(data=data, freshness=DataFreshness(provider="lxns", operation="test"))


def _player(*, empty=False):
    profile = MaimaiProfile.model_validate({
        "name": "tester", "rating": 15000, "frame": {"id": 1},
        "trophy": {"color": "Normal", "name": "Test Trophy"},
        "name_plate": {"id": 1}, "icon": {"id": 1},
        "class_rank": 1, "course_rank": 1,
    })
    standard = [] if empty else [MaimaiScore(id=1, type="standard", level_index=3, achievements=100.5)]
    dx = [] if empty else [MaimaiScore(id=2, type="dx", level_index=3, achievements=100.0)]
    return SimpleNamespace(
        friend_code="10001",
        profile=AsyncMock(return_value=_result(profile)),
        bests=AsyncMock(return_value=_result(MaimaiBests(standard=standard, dx=dx))),
        recents=AsyncMock(return_value=_result(MaimaiRecents(scores=standard))),
        trend=AsyncMock(return_value=_result(MaimaiTrend())),
    )


@pytest.mark.parametrize("handler", ["b50", "r50", "profile"])
async def test_player_cards_accept_normalized_sdk_models(loaded_chiffon_bot, monkeypatch, handler):
    module = importlib.import_module(f"src.plugins.chiffon_bot.domains.maimai.handlers.{handler}")
    player = _player()
    render_name = "render_r50_img" if handler == "r50" else "render_b50_img"
    render = AsyncMock(return_value=b"card")
    monkeypatch.setattr(module.mai_bg_draw, render_name, render)
    if handler != "profile":
        enhance = AsyncMock(side_effect=lambda scores: [{**score, "enhanced": True} for score in scores])
        monkeypatch.setattr(module, "enhance_scores", enhance)

    response = await getattr(module, handler)(player, {"X-Test": "1"}, "123", 42)

    assert response.image == b"card"
    assert response.reply_to == 42
    assert response.suffix
    player.profile.assert_awaited_once_with(headers={"X-Test": "1"})
    args = render.await_args.kwargs
    assert args["user_data"]["data"]["name"] == "tester"
    assert args["user_data"]["data"]["frame"]["id"] == 1
    if handler == "b50":
        assert args["b35_data"][0]["id"] == 1
        assert args["b15_data"][0]["id"] == 2
        assert args["b35_data"][0]["enhanced"] is True
    elif handler == "r50":
        assert args["recent_data"][0]["id"] == 1
        assert args["recent_data"][0]["enhanced"] is True
    else:
        assert args["height"] == 536


@pytest.mark.parametrize("handler", ["b50", "r50"])
async def test_empty_scores_still_render_player_card(loaded_chiffon_bot, monkeypatch, handler):
    module = importlib.import_module(f"src.plugins.chiffon_bot.domains.maimai.handlers.{handler}")
    render = AsyncMock(return_value=b"empty-card")
    monkeypatch.setattr(module.mai_bg_draw, "render_r50_img" if handler == "r50" else "render_b50_img", render)
    monkeypatch.setattr(module, "enhance_scores", AsyncMock(side_effect=lambda scores: scores))

    response = await getattr(module, handler)(_player(empty=True), {}, "123", 42)

    assert response.image == b"empty-card"
    args = render.await_args.kwargs
    if handler == "b50":
        assert args["b35_data"] == args["b15_data"] == []
    else:
        assert args["recent_data"] == []


@pytest.mark.parametrize("handler, operation, model", [
    ("b50", "bests", MaimaiBests), ("r50", "recents", MaimaiRecents),
    ("profile", "profile", MaimaiProfile), ("trend", "trend", MaimaiTrend),
])
@pytest.mark.parametrize("failure", ["transport", "business"])
async def test_query_failures_return_text_before_rendering(
    loaded_chiffon_bot, monkeypatch, handler, operation, model, failure,
):
    module = importlib.import_module(f"src.plugins.chiffon_bot.domains.maimai.handlers.{handler}")
    player = _player()
    if failure == "transport":
        getattr(player, operation).side_effect = TimeoutError("request timed out")
    else:
        getattr(player, operation).return_value = _result(model.model_validate({
            "code": 403, "success": False, "message": "成绩未公开",
        }))
    render = AsyncMock()
    if handler == "trend":
        render = Mock()
        monkeypatch.setattr(module.plt, "figure", render)
        response = await module.generate_trend_plot(player, {})
    else:
        monkeypatch.setattr(module.mai_bg_draw, "render_r50_img" if handler == "r50" else "render_b50_img", render)
        response = await getattr(module, handler)(player, {}, "123", 42)

    assert response.image is None
    assert "查询失败" in response.text
    if failure == "business":
        assert "成绩未公开" in response.text
    render.assert_not_called()


@pytest.mark.parametrize("legacy_totals", [False, True])
async def test_trend_reads_typed_entries_and_keeps_series_aligned(
    loaded_chiffon_bot, monkeypatch, legacy_totals,
):
    module = importlib.import_module("src.plugins.chiffon_bot.domains.maimai.handlers.trend")
    standard, dx = ("standard_total", "dx_total") if legacy_totals else ("standard", "dx")
    player = _player()
    player.trend.return_value = _result(MaimaiTrend.model_validate({"trend": [
        {"date": "2026-10-01", "total": 15000, standard: 10000, dx: 5000},
        {"date": "2026-10-02", "total": 15050},
        {"date": "2026-10-03", "total": 15100, standard: 10100, dx: 5000},
    ]}))
    plot = Mock(wraps=module.plt.plot)
    annotate = Mock(wraps=module.plt.annotate)
    monkeypatch.setattr(module.plt, "plot", plot)
    monkeypatch.setattr(module.plt, "annotate", annotate)
    monkeypatch.setattr(module.plt, "savefig", lambda stream, **kwargs: stream.write(b"trend"))

    response = await module.generate_trend_plot(player, {})

    assert response.image == b"trend"
    assert plot.call_args.args[0] == [datetime(2026, 10, 1), datetime(2026, 10, 3)]
    assert plot.call_args.args[1] == [15000, 15100]
    assert annotate.call_args.args[0] == "B35:10000\n B15:5000"


async def test_empty_trend_returns_no_data_text(loaded_chiffon_bot, monkeypatch):
    module = importlib.import_module("src.plugins.chiffon_bot.domains.maimai.handlers.trend")
    render = Mock()
    monkeypatch.setattr(module.plt, "figure", render)
    response = await module.generate_trend_plot(_player(), {})
    assert response.image is None
    assert "暂无" in response.text
    render.assert_not_called()


@pytest.mark.parametrize("empty", [False, True])
async def test_activity_updater_reads_normalized_recent_scores(loaded_chiffon_bot, monkeypatch, empty):
    from src.plugins.chiffon_bot.domains import auto_score_updater

    player = _player(empty=empty)
    monkeypatch.setattr(type(auto_score_updater.lxns_client.data.players.maimai), "default_player", AsyncMock(return_value=player))

    records = await auto_score_updater.get_recent_records("123", {"X-Test": "1"})

    assert [record["id"] for record in records] == ([] if empty else [1])
    player.recents.assert_awaited_once_with(headers={"X-Test": "1"})


async def test_activity_updater_discards_scores_from_failed_response(loaded_chiffon_bot, monkeypatch):
    from src.plugins.chiffon_bot.domains import auto_score_updater

    player = _player()
    player.recents.return_value = _result(MaimaiRecents(
        scores=[MaimaiScore(id=1)], code=403, success=False, message="成绩未公开",
    ))
    monkeypatch.setattr(type(auto_score_updater.lxns_client.data.players.maimai), "default_player", AsyncMock(return_value=player))

    assert await auto_score_updater.get_recent_records("123", {}) == []
