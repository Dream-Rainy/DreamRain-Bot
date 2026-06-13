"""Bot-side adapter for maimai external catalog fetching."""

from nonebot import get_plugin_config, logger
from src.chiffon_data.core.context import CatalogContext
from src.chiffon_data.games.maimai.data_fetcher import (
    build_maimai_jacket_image_name,
    fetch_maimai_catalog,
)
from ....config import Config
from ....infra.http import http_client
from ....integrations.lxns.plugin_data import plugin_data
from .song_data_sync import sync_mai_map_data, sync_mai_map_treasure_data


async def fetch_maimai_raw_data():
    plugin_config = get_plugin_config(Config)
    context = CatalogContext(
        http_get_json=http_client.get_json,
        ingame_data_base_dir=plugin_config.ingame_data_base_dir,
        headers=plugin_data.headers,
        logger=logger,
    )
    result = await fetch_maimai_catalog(
        context,
        current_data_version=plugin_data.data_version,
        sync_map_data=sync_mai_map_data,
        sync_map_treasure_data=sync_mai_map_treasure_data,
    )
    plugin_data.data_version = result.data_version
    return result.songs


__all__ = ["build_maimai_jacket_image_name", "fetch_maimai_raw_data"]
