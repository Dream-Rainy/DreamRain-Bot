"""CHUNITHM random-song handler wrapper."""

from __future__ import annotations

from typing import Optional

from ....shared.bot_response import BotResponse
from ....shared.handlers.generic_random_song import (
    generic_random_song,
    get_songs_by_difficulty_range,
    parse_difficulty_range,
)
from ..chunithm_adapter import get_chunithm_adapter


async def chuni_random_song(
    range_str: Optional[str],
    user_id: str,
    message_id: int,
) -> BotResponse:
    """Randomly pick a CHUNITHM song, optionally filtered by difficulty range."""

    return await generic_random_song(range_str, user_id, message_id, get_chunithm_adapter())


__all__ = [
    "chuni_random_song",
    "get_songs_by_difficulty_range",
    "parse_difficulty_range",
]
