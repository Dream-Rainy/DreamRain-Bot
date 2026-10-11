import asyncio
import json
from types import SimpleNamespace

import pytest


@pytest.fixture()
def summary(app):
    from src.plugins.priconne.clanbattle import summary
    from src.plugins.priconne.clanbattle.period import BattlePeriod

    return summary, BattlePeriod(42, 1000, 2000)


async def test_failed_page_restarts_from_disk_with_frozen_input_and_never_resends_finished_pages(summary, tmp_path, monkeypatch):
    module, period = summary
    path = tmp_path / "summary_send.json"
    prepared, sent = [], []

    async def prepare():
        prepared.append(1)
        return {"period_id": 42, "value": "original"}

    async def render(payload, page):
        return page + ":" + payload["value"]

    async def fail(page, message):
        if page == "bosses":
            raise RuntimeError("send failed")
        sent.append(message)

    with pytest.raises(RuntimeError, match="send failed"):
        await module.send_summary(path, period, 2300, prepare, render, fail)
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["sent"] == ["overview", "members"]
    assert saved["payload"]["value"] == "original"
    monkeypatch.setattr(module, "_send_lock", asyncio.Lock())

    async def unexpected_prepare():
        raise AssertionError("重启续发必须使用已冻结输入")

    async def success(page, message):
        sent.append(message)

    assert await module.send_summary(path, period, 2600, unexpected_prepare, render, success)
    assert sent == [page + ":original" for page in module.REVIEW_PAGES]
    assert prepared == [1]
    assert await module.send_summary(path, period, 2900, unexpected_prepare, render, success)
    assert len(sent) == 5


async def test_outside_window_and_corrupt_receipt_send_nothing(summary, tmp_path):
    module, period = summary
    path = tmp_path / "summary_send.json"

    async def unexpected(*args):
        raise AssertionError("禁止准备或发送")

    assert not await module.send_summary(path, period, period.end + 299, unexpected, unexpected, unexpected)
    assert not path.exists()
    assert not await module.send_summary(path, period, period.end + 86400, unexpected, unexpected, unexpected)
    path.write_text(json.dumps(dict(period_id=42, sent=["members"], payload={"period_id": 42})), encoding="utf-8")
    with pytest.raises(ValueError, match="损坏"):
        await module.send_summary(path, period, 2300, unexpected, unexpected, unexpected)


async def test_overlapping_attempts_only_send_one_set(summary, tmp_path):
    module, period = summary
    sent = []

    async def prepare():
        return {"period_id": 42}

    async def render(payload, page):
        return page

    async def send(page, message):
        await asyncio.sleep(0)
        sent.append(page)

    results = await asyncio.gather(*[module.send_summary(tmp_path / "summary_send.json", period, 2300,
                                                        prepare, render, send) for _ in range(2)])
    assert results == [True, True] and sent == list(module.REVIEW_PAGES)


async def test_broadcast_uses_registered_bot_and_skips_disabled_foreign_and_unregistered_groups(summary, monkeypatch):
    module, period = summary
    from src.plugins.priconne import clanbattle
    from src.plugins.permission_admin import core

    sent = []

    async def schedule(**kwargs):
        return period

    async def send(bot, group_id, event, now):
        sent.append((bot, group_id, event.id))

    monkeypatch.setattr(clanbattle.time, "time", lambda: 2300)
    monkeypatch.setattr(clanbattle, "get_period", schedule)
    monkeypatch.setattr(clanbattle, "get_bot", lambda self_id: "bot:" + self_id)
    monkeypatch.setattr(clanbattle, "_send_event_summary", send)
    monkeypatch.setattr(core, "get_permission_manager", lambda: SimpleNamespace(get_snapshot=lambda pid: {"blocked_groups": [2]}))
    monkeypatch.setattr(clanbattle, "run_group", {
        1: {"summary": {"period_id": 42, "self_id": "10000"}},
        2: {"summary": {"period_id": 42, "self_id": "20000"}},
        3: {"summary": {"period_id": 41, "self_id": "30000"}},
        4: {"self_id": "40000", "qq_id": 9},
    })
    await clanbattle.final_summary_broadcast()
    assert sent == [("bot:10000", 1, 42)]
