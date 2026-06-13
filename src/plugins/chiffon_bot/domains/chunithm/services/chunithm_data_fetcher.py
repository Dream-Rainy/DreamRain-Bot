"""Bot-side adapter for CHUNITHM external catalog fetching."""

from nonebot import get_plugin_config, logger
from src.chiffon_data.core.context import CatalogContext
from src.chiffon_data.games.chunithm.data_fetcher import (
    build_chuni_jacket_image_name,
    fetch_chunithm_catalog,
    merge_chuni_arcade_and_lxns,
)

from ....config import Config
from ....infra.http import http_client
from ....integrations.lxns.plugin_data import plugin_data


async def fetch_chunithm_raw_data():
    plugin_config = get_plugin_config(Config)
    context = CatalogContext(
        http_get_json=http_client.get_json,
        ingame_data_base_dir=plugin_config.ingame_data_base_dir,
        headers=plugin_data.headers,
        logger=logger,
    )
    return await fetch_chunithm_catalog(context)


__all__ = [
    "build_chuni_jacket_image_name",
    "fetch_chunithm_raw_data",
    "merge_chuni_arcade_and_lxns",
]
