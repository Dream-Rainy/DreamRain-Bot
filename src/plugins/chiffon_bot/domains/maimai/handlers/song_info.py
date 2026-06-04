"""Maimai song-info handler wrapper."""

from __future__ import annotations

from typing import Any

from ....shared.bot_response import BotResponse
from ....shared.handlers.generic_song_info import generic_song_info
from ..maimai_adapter import get_maimai_adapter


async def song_info(song_query: Any, user_id: str, message_id: int) -> BotResponse:
    """Query and render maimai song info."""

    return await generic_song_info(
        song_query,
        user_id,
        message_id,
        get_maimai_adapter(),
    )
