"""Bot-side LXNS integration facade."""

from __future__ import annotations

from nonebot import get_plugin_config, logger

from arcade_helper import ArcadeHelperClient
from arcade_helper.integrations.lxns.oauth_client import OauthClient
from arcade_helper.integrations.lxns.sse import SseRelayClient
from arcade_helper.storage.tortoise import TortoiseAccountStore, TortoiseSongStore

from ...config import Config
from ...infra.http import http_client
from .catalog import BotCatalogClient


async def _get_json(*args, **kwargs):
    return await http_client.get_json(*args, **kwargs)


async def _post_json(*args, **kwargs):
    return await http_client.post_json(*args, **kwargs)


class BotLxnsClient:
    """Single bot-wired entrypoint for LXNS data, OAuth, SSE, and storage."""

    def __init__(self) -> None:
        self._config = get_plugin_config(Config)
        self.accounts = TortoiseAccountStore()
        self.songs = TortoiseSongStore(logger=logger)
        self.data = ArcadeHelperClient(
            http_get_json=_get_json,
            http_post_json=_post_json,
            ingame_data_base_dir=self._config.ingame_data_base_dir,
            lxns_base_url=getattr(self._config, "lxns_base_url", "https://maimai.lxns.net"),
            headers={},
            logger=logger,
            lxns_client_id=getattr(self._config, "lxns_client_id", ""),
            lxns_client_secret=getattr(self._config, "lxns_client_secret", ""),
            lxns_oauth_redirect_uri=getattr(self._config, "lxns_oauth_redirect_uri", ""),
            lxns_oauth_scope=getattr(self._config, "lxns_oauth_scope", ""),
            lxns_oauth_state_ttl_seconds=getattr(self._config, "lxns_oauth_state_ttl_seconds", 600),
            lxns_oauth_relay_url=getattr(self._config, "lxns_oauth_relay_url", ""),
            account_store=self.accounts,
            song_store=self.songs,
        )
        if self.data.lxns.oauth is None:
            raise RuntimeError("LXNS OAuth client was not initialized")

        self.lxns = self.data.lxns
        self.maimai = self.data.maimai
        self.chunithm = self.data.chunithm
        self.oauth: OauthClient = self.data.lxns.oauth
        self.sse = SseRelayClient(
            relay_url=getattr(self._config, "lxns_oauth_relay_url", ""),
            relay_token=getattr(self._config, "lxns_oauth_relay_token", ""),
            logger=logger,
        )
        self.catalog = BotCatalogClient(
            self.data,
            song_store=self.songs,
            logger=logger,
            auto_sync_enabled=getattr(self._config, "song_data_auto_sync_enabled", True),
            auto_sync_interval_seconds=getattr(self._config, "song_data_auto_sync_interval_seconds", 86400),
            auto_sync_startup_delay_seconds=getattr(
                self._config,
                "song_data_auto_sync_startup_delay_seconds",
                300,
            ),
        )


lxns_client = BotLxnsClient()

__all__ = ["BotLxnsClient", "lxns_client"]
