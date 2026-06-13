"""Bot-side LXNS OAuth client wiring."""

from nonebot import get_plugin_config
from src.chiffon_data.integrations.lxns.oauth_client import OauthClient

from ...config import Config
from ...infra.http import http_client

plugin_config = get_plugin_config(Config)


async def _post_json(*args, **kwargs):
    return await http_client.post_json(*args, **kwargs)


oa_client = OauthClient(
    http_post_json=_post_json,
    client_id=plugin_config.lxns_client_id,
    client_secret=plugin_config.lxns_client_secret,
    base_url=getattr(plugin_config, "lxns_base_url", "https://maimai.lxns.net"),
    redirect_uri=getattr(plugin_config, "lxns_oauth_redirect_uri", ""),
    scope=getattr(plugin_config, "lxns_oauth_scope", ""),
    state_ttl_seconds=getattr(plugin_config, "lxns_oauth_state_ttl_seconds", 600),
    relay_url=getattr(plugin_config, "lxns_oauth_relay_url", ""),
)

__all__ = ["OauthClient", "oa_client"]
