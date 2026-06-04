"""CHUNITHM song-info handler wrapper."""

from __future__ import annotations

from ....shared.bot_response import BotResponse
from ....shared.handlers.generic_song_info import generic_song_info
from ..chunithm_adapter import get_chunithm_adapter


async def chuni_song_info_msg(song_query: str | int, message_id: int) -> BotResponse:
    """Query and render CHUNITHM song info."""

    return await generic_song_info(
        song_query,
        "",
        message_id,
        get_chunithm_adapter(),
    )
