from __future__ import annotations

import asyncio
from typing import Any

import pytest

from arcade_helper import ArcadeHelperClient


class _Logger:
    def debug(self, *_args: Any, **_kwargs: Any) -> None:
        pass

    def info(self, *_args: Any, **_kwargs: Any) -> None:
        pass

    def warning(self, *_args: Any, **_kwargs: Any) -> None:
        pass

    def error(self, *_args: Any, **_kwargs: Any) -> None:
        pass


async def _get_json(_url: str, **_kwargs: Any) -> dict[str, Any]:
    return {}


def _catalog(loaded_chiffon_bot):
    from src.plugins.chiffon_bot.integrations.lxns.catalog import BotCatalogClient
    from arcade_helper.storage.tortoise import TortoiseSongStore

    data = ArcadeHelperClient(http_get_json=_get_json)
    return BotCatalogClient(
        data,
        song_store=TortoiseSongStore(logger=_Logger()),
        logger=_Logger(),
        auto_sync_enabled=True,
        auto_sync_interval_seconds=60,
        auto_sync_startup_delay_seconds=0,
        background_refresh_delay_seconds=0,
    )


@pytest.mark.asyncio
async def test_catalog_background_refresh_is_single_flight(loaded_chiffon_bot) -> None:
    catalog = _catalog(loaded_chiffon_bot)
    release = asyncio.Event()

    async def fake_sync() -> None:
        await release.wait()

    catalog.sync_song_data_from_remote = fake_sync  # type: ignore[method-assign]

    assert catalog.start_background_refresh() is True
    assert catalog.start_background_refresh() is False

    release.set()
    assert catalog._refresh_task is not None
    await catalog._refresh_task
    await asyncio.sleep(0)

    assert catalog._refresh_task is None


@pytest.mark.asyncio
async def test_manual_refresh_starts_auto_sync(loaded_chiffon_bot, monkeypatch: pytest.MonkeyPatch) -> None:
    catalog = _catalog(loaded_chiffon_bot)
    calls: list[str] = []

    async def fake_load() -> tuple[bool, str]:
        return True, "loaded"

    monkeypatch.setattr(catalog, "load_song_data_from_db", fake_load)
    monkeypatch.setattr(catalog, "start_background_refresh", lambda: True)
    monkeypatch.setattr(catalog, "start_auto_sync", lambda: calls.append("auto") or True)

    assert await catalog.refresh_song_data(manual=True) == (True, "loaded；已启动后台同步")
    assert calls == ["auto"]


def test_lxns_client_exposes_catalog(loaded_chiffon_bot) -> None:
    from src.plugins.chiffon_bot.integrations.lxns.client import lxns_client

    assert lxns_client.catalog.data is lxns_client.data
    assert lxns_client.catalog.service is lxns_client.data.catalog


@pytest.mark.asyncio
async def test_bot_catalog_query_delegates_to_data_catalog(loaded_chiffon_bot, monkeypatch: pytest.MonkeyPatch) -> None:
    catalog = _catalog(loaded_chiffon_bot)
    calls: list[tuple[str, int]] = []

    async def fake_get_song_by_id(game_code: str, song_id: int):
        calls.append((game_code, song_id))
        return {"id": song_id}

    monkeypatch.setattr(catalog.service, "get_song_by_id", fake_get_song_by_id)

    assert await catalog.get_song_by_id("maimai", 123) == {"id": 123}
    assert calls == [("maimai", 123)]
