"""Bot-side adapter for LXNS player data APIs."""

from nonebot import get_plugin_config, logger
from src.chiffon_data.core.context import CatalogContext
from src.chiffon_data.integrations.lxns import player_api as lxns_player_api

from ...config import Config
from ...infra.http import http_client


def _context(headers: dict | None = None) -> CatalogContext:
    plugin_config = get_plugin_config(Config)
    return CatalogContext(
        http_get_json=http_client.get_json,
        ingame_data_base_dir=plugin_config.ingame_data_base_dir,
        headers=dict(headers or {}),
        logger=logger,
    )


async def get_b50_data(friend_code: str, headers: dict) -> dict:
    return await lxns_player_api.get_b50_data(_context(headers), friend_code, headers)


async def get_user_data(friend_code: str, headers: dict) -> dict:
    return await lxns_player_api.get_user_data(_context(headers), friend_code, headers)


async def get_r50_data(friend_code: str, headers: dict) -> dict:
    return await lxns_player_api.get_r50_data(_context(headers), friend_code, headers)


async def get_trend_data(friend_code: str, headers: dict) -> dict:
    return await lxns_player_api.get_trend_data(_context(headers), friend_code, headers)


__all__ = ["get_b50_data", "get_r50_data", "get_trend_data", "get_user_data"]
