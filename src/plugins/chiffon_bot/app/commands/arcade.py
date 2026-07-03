"""Generic arcade-songs catalog commands."""

from __future__ import annotations

from typing import Any

from nonebot.adapters import Event, Message
from nonebot.params import CommandArg

from arcade_helper.search import SongQueryResult

from ...integrations.lxns.client import lxns_client
from ...shared.bot_response import BotResponse
from ...shared.handlers.song_text import format_song_text_detail, load_song_jacket_bytes
from ._response import finish_with


def parse_arcade_song_args(text: str) -> tuple[str, str] | None:
    parts = text.strip().split(maxsplit=1)
    if len(parts) != 2:
        return None
    game_code, query = parts[0].strip().lower(), parts[1].strip()
    if not game_code or not query:
        return None
    return game_code, query


async def query_arcade_song(game_code: str, query: str | int, message_id: int) -> BotResponse:
    try:
        results = await lxns_client.data.catalog.arcade_songs.search(game_code, query)
    except Exception as e:  # noqa: BLE001
        return BotResponse(text=f"查询 {game_code} 曲库失败: {e}", reply_to=message_id)
    try:
        sites = await lxns_client.data.catalog.arcade_songs.sites()
    except Exception:  # noqa: BLE001
        sites = []
    return await build_arcade_song_response(game_code, results, message_id, arcade_sites=sites)


async def build_arcade_song_response(
    game_code: str,
    results: list[SongQueryResult],
    message_id: int,
    *,
    arcade_sites: list[dict] | None = None,
) -> BotResponse:
    if not results:
        return BotResponse(text=f"未找到 {game_code} 曲目", reply_to=message_id)

    perfect = [result for result in results if result.match_score == 100.0]
    if not perfect and len(results) > 1:
        lines = [f"[{game_code}] 找到多个近似结果，请使用更精确的关键词或 ID 查询：", ""]
        for result in results[:5]:
            artist = _get_text(result.song_data, "artist")
            suffix = f"  {artist}" if artist else ""
            lines.append(f"[{result.song_id}] {result.title}{suffix} ({result.match_score:.0f}%)")
        if len(results) > 5:
            lines.append(f"...还有 {len(results) - 5} 个结果")
        return BotResponse(text="\n".join(lines), reply_to=message_id)

    result = perfect[0] if perfect else results[0]
    image = await load_song_jacket_bytes(game_code, result, arcade_sites=arcade_sites)
    return BotResponse(
        text="\n".join(format_song_text_detail(game_code, result)),
        image=image,
        reply_to=message_id,
    )


def register_arcade_commands(group) -> None:
    song_cmd = group.command("song", force_whitespace=True)

    @song_cmd.handle()
    async def _song(event: Event, args: Message = CommandArg()):
        parsed = parse_arcade_song_args(args.extract_plain_text())
        if parsed is None:
            await song_cmd.finish("用法：/arcade.song <game_code> <歌曲名/ID>")
        game_code, query = parsed
        await finish_with(await query_arcade_song(game_code, query, event.message_id))


def _get_text(obj: Any, attr: str) -> str:
    return str(getattr(obj, attr, "") or "").strip()


__all__ = [
    "build_arcade_song_response",
    "parse_arcade_song_args",
    "query_arcade_song",
    "register_arcade_commands",
]
