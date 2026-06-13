"""LXNS 玩家数据相关 API 调用（集成层）。"""

from ...core.context import CatalogContext
from .constants import (
    maimai_player_bests_url,
    maimai_player_recents_url,
    maimai_player_trend_url,
    maimai_player_url,
)


async def get_b50_data(context: CatalogContext, friend_code: str, headers: dict | None = None) -> dict:
    return await context.get_json(
        maimai_player_bests_url(friend_code),
        headers=headers or context.headers,
    )


async def get_user_data(context: CatalogContext, friend_code: str, headers: dict | None = None) -> dict:
    return await context.get_json(
        maimai_player_url(friend_code),
        headers=headers or context.headers,
    )


async def get_r50_data(context: CatalogContext, friend_code: str, headers: dict | None = None) -> dict:
    return await context.get_json(
        maimai_player_recents_url(friend_code),
        headers=headers or context.headers,
    )


async def get_trend_data(context: CatalogContext, friend_code: str, headers: dict | None = None) -> dict:
    return await context.get_json(
        maimai_player_trend_url(friend_code),
        headers=headers or context.headers,
    )


__all__ = ["get_b50_data", "get_r50_data", "get_trend_data", "get_user_data"]
