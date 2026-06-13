from __future__ import annotations

"""LXNS 相关 URL/路径常量。

统一收口 `https://maimai.lxns.net` 的硬编码，方便后续替换环境或改版。
"""

from urllib.parse import urlencode

LXNS_BASE_URL = "https://maimai.lxns.net"


def _base(base_url: str | None = None) -> str:
    return (base_url or LXNS_BASE_URL).rstrip("/")

# ---- public site / config ----


def site_config_url() -> str:
    return f"{_base()}/api/v0/site/config"


def maimai_song_list_url(*, notes: bool = True) -> str:
    qs = urlencode({"notes": "true" if notes else "false"})
    return f"{_base()}/api/v0/maimai/song/list?{qs}"


def maimai_song_collections_url(song_id: int) -> str:
    """获取乐曲的收藆信息（奖杯、称号等）"""
    return f"{_base()}/api/v0/maimai/song-collections/{song_id}"


def maimai_alias_list_url() -> str:
    """获取 maimai 乐曲别名列表（LXNS 数据源）"""
    return f"{_base()}/api/v0/maimai/alias/list"


def chunithm_alias_list_url() -> str:
    """获取 chunithm 乐曲别名列表（LXNS 数据源）"""
    return f"{_base()}/api/v0/chunithm/alias/list"


def chunithm_song_list_url(*, notes: bool = True) -> str:
    qs = urlencode({"notes": "true" if notes else "false"})
    return f"{_base()}/api/v0/chunithm/song/list?{qs}"


# ---- player (public) ----

def maimai_player_url(friend_code: str) -> str:
    return f"{_base()}/api/v0/maimai/player/{friend_code}"


def maimai_player_bests_url(friend_code: str) -> str:
    return f"{_base()}/api/v0/maimai/player/{friend_code}/bests"


def maimai_player_recents_url(friend_code: str) -> str:
    return f"{_base()}/api/v0/maimai/player/{friend_code}/recents"


def maimai_player_trend_url(friend_code: str) -> str:
    return f"{_base()}/api/v0/maimai/player/{friend_code}/trend"


def maimai_player_by_qq_url(qq: str) -> str:
    return f"{_base()}/api/v0/maimai/player/qq/{qq}"


def chunithm_player_by_qq_url(qq: str) -> str:
    return f"{_base()}/api/v0/chunithm/player/qq/{qq}"


# ---- user endpoints (OAuth required) ----


def user_maimai_player_url() -> str:
    return f"{_base()}/api/v0/user/maimai/player"


def user_chunithm_player_url() -> str:
    return f"{_base()}/api/v0/user/chunithm/player"


# ---- OAuth ----


def oauth_authorize_url(*, base_url: str | None = None) -> str:
    return f"{_base(base_url)}/oauth/authorize"


def oauth_authorize_with_params(
    *,
    client_id: str,
    redirect_uri: str,
    state: str,
    scope: str = "",
    response_type: str = "code",
    base_url: str | None = None,
) -> str:
    qs = {
        "response_type": response_type,
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
    }
    if scope:
        qs["scope"] = scope
    return f"{oauth_authorize_url(base_url=base_url)}?{urlencode(qs)}"


def oauth_token_url(*, base_url: str | None = None) -> str:
    return f"{_base(base_url)}/api/v0/oauth/token"


# ---- 第三方别名数据源 ----

YUZUCHAN_BASE_URL = "https://www.yuzuchan.moe"


def yuzuchan_maimai_alias_url() -> str:
    """柚子查 maimai 别名数据接口"""
    return f"{YUZUCHAN_BASE_URL}/api/maimaidx/maimaidxalias"
