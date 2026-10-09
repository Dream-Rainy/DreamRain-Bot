"""Bot-side LXNS integration facade."""

from __future__ import annotations

from pathlib import Path

from nonebot import get_plugin_config, logger
from nonebot.permission import SUPERUSER
from src.plugins.platform_adapter import PlatformContext

from arcade_helper import ArcadeHelperClient
from arcade_helper.integrations.lxns.oauth_client import OauthClient
from arcade_helper.integrations.lxns.sse import SseRelayClient
from arcade_helper.storage.tortoise import TortoiseAccountStore, TortoiseSongStore, TortoiseCatalogStore

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
        self.identities = TortoiseCatalogStore(enable_aliases=True)
        self._alias_actors: dict[int, bool] = {}
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
            catalog_store=self.identities,
            alias_policy=self._alias_policy,
            local_data_dir=Path("data") / "chiffon_bot" / "arcade-helper",
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

    def _alias_policy(self, user_id: int, action: str, game_code: str | None) -> bool:
        if user_id not in self._alias_actors:
            return False
        return action == "submit" or self._alias_actors[user_id]

    async def alias_actor(self, bot, event) -> int:
        context = PlatformContext.from_event(event, bot)
        platform = "qq" if "onebot" in context.platform else context.platform
        if platform == "unknown":
            raise ValueError("无法识别当前平台身份")
        user = await self.data.users.from_platform(platform, event.get_user_id())
        # Only the authenticated adapter event grants roles, never command text.
        self._alias_actors[user.user_id] = bool(await SUPERUSER(bot, event))
        return user.user_id


lxns_client = BotLxnsClient()

__all__ = ["BotLxnsClient", "lxns_client"]
