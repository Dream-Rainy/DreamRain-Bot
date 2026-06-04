"""Maimai random-song handler wrapper."""

from __future__ import annotations

from typing import Optional

from ....shared.bot_response import BotResponse
from ....shared.handlers.generic_random_song import (
    generic_random_song,
    get_songs_by_difficulty_range,
    parse_difficulty_range,
)
from ..maimai_adapter import get_maimai_adapter


async def random_song(range_str: Optional[str], user_id: str, message_id: int) -> BotResponse:
    """Randomly pick a maimai song, optionally filtered by difficulty range."""

    return await generic_random_song(range_str, user_id, message_id, get_maimai_adapter())


__all__ = [
    "get_songs_by_difficulty_range",
    "parse_difficulty_range",
    "random_song",
]
