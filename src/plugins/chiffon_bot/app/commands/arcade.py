"""Generic arcade-songs catalog commands."""

from __future__ import annotations

import asyncio
from typing import Any

from nonebot.adapters import Event, Message
from nonebot.params import CommandArg

from arcade_helper.search import MatchType, SongQueryResult

from ...integrations.lxns.client import lxns_client
from ...shared.bot_response import BotResponse
from ...shared.handlers.song_text import format_song_text_detail, load_song_jacket_bytes
from ...shared.search.catalog_search import search_song_with_audit
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
        results = await search_song_with_audit(query, game_code=game_code)
    except Exception as e:  # noqa: BLE001
        return BotResponse(text=f"查询 {game_code} 曲库失败: {e}", reply_to=message_id)
    try:
        sites = await lxns_client.data.catalog.arcade_songs.sites()
    except Exception:  # noqa: BLE001
        sites = []
    return await build_arcade_song_response(game_code, results, message_id, arcade_sites=sites)


async def query_arcade_song_games(query: str, message_id: int) -> BotResponse:
    try:
        sites = await lxns_client.data.catalog.arcade_songs.sites()
    except Exception as e:  # noqa: BLE001
        return BotResponse(text=f"获取 arcade-songs 游戏列表失败: {e}", reply_to=message_id)

    game_codes = list(
        dict.fromkeys(
            str(site.get("gameCode") or "").strip().lower()
            for site in sites
            if isinstance(site, dict) and str(site.get("gameCode") or "").strip()
        )
    )
    if not game_codes:
        return BotResponse(text="arcade-songs 没有可查询的游戏", reply_to=message_id)

    results_by_game = await asyncio.gather(
        *(
            lxns_client.catalog.search.search_song(query, game_code=game_code)
            for game_code in game_codes
        ),
        return_exceptions=True,
    )
    exact_hits: dict[str, list[SongQueryResult]] = {}
    suggestions: list[tuple[str, SongQueryResult]] = []
    failed_games: list[str] = []

    for game_code, results in zip(game_codes, results_by_game, strict=True):
        if isinstance(results, asyncio.CancelledError):
            raise results
        if isinstance(results, Exception):
            failed_games.append(game_code)
            continue
        exact = [
            result
            for result in results
            if result.match_score == 100.0 and result.match_type is not MatchType.EXACT_ID
        ]
        if exact:
            exact_hits[game_code] = exact
        elif (
            results
            and results[0].match_type is not MatchType.EXACT_ID
            and results[0].match_score >= 80.0
        ):
            suggestions.append((game_code, results[0]))

    if exact_hits:
        lines = [f"《{query}》在 {len(exact_hits)} 个游戏中找到："]
        for game_code in game_codes:
            for result in exact_hits.get(game_code, []):
                lines.append(f"[{game_code}] [{result.song_id}] {result.title}")
    elif suggestions:
        lines = [f"未找到《{query}》的精确匹配，以下是近似结果："]
        ranked_suggestions = sorted(
            suggestions,
            key=lambda item: item[1].match_score,
            reverse=True,
        )[:10]
        for game_code, result in ranked_suggestions:
            lines.append(
                f"[{game_code}] [{result.song_id}] {result.title} ({result.match_score:.0f}%)"
            )
    else:
        message = (
            f"在可访问的曲库中未找到《{query}》"
            if failed_games
            else f"未在 arcade-songs 曲库中找到《{query}》"
        )
        lines = [message]

    if failed_games:
        lines.append("曲库查询失败：" + "、".join(failed_games))
    return BotResponse(text="\n".join(lines), reply_to=message_id)


async def query_arcade_artist(game_code: str, artist: str, message_id: int) -> BotResponse:
    gc, query = game_code.strip().lower(), artist.strip()
    if not gc or not query:
        return BotResponse(text="用法：/arcade.artist <game_code> <曲师名>", reply_to=message_id)
    try:
        songs = await lxns_client.catalog.load_all_songs(gc)
    except Exception as e:  # noqa: BLE001
        return BotResponse(text=f"查询 {gc} 曲库失败: {e}", reply_to=message_id)

    matches = [
        (song_id, song)
        for song_id, song in songs.items()
        if query.casefold() in _get_text(song, "artist").casefold()
    ]
    matches.sort(key=lambda item: (_get_text(item[1], "title").casefold(), item[0]))
    if not matches:
        return BotResponse(text=f"{gc} 曲库中没有曲师名包含“{query}”的歌曲", reply_to=message_id)

    lines = [f"[{gc}] 曲师名包含“{query}”的歌曲（{len(matches)} 首）："]
    lines.extend(f"[{song_id}] {_get_text(song, 'title')}" for song_id, song in matches)
    return BotResponse(text="\n".join(lines), reply_to=message_id)


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

    games_cmd = group.command("games", force_whitespace=True)

    @games_cmd.handle()
    async def _games(event: Event, args: Message = CommandArg()):
        query = args.extract_plain_text().strip()
        if not query:
            await games_cmd.finish("用法：/arcade.games <歌曲名>")
        await finish_with(await query_arcade_song_games(query, event.message_id))

    artist_cmd = group.command("artist", force_whitespace=True)

    @artist_cmd.handle()
    async def _artist(event: Event, args: Message = CommandArg()):
        parsed = parse_arcade_song_args(args.extract_plain_text())
        if parsed is None:
            await artist_cmd.finish("用法：/arcade.artist <game_code> <曲师名>")
        game_code, artist = parsed
        await finish_with(await query_arcade_artist(game_code, artist, event.message_id))


def _get_text(obj: Any, attr: str) -> str:
    return str(getattr(obj, attr, "") or "").strip()


__all__ = [
    "build_arcade_song_response",
    "parse_arcade_song_args",
    "query_arcade_artist",
    "query_arcade_song",
    "query_arcade_song_games",
    "register_arcade_commands",
]
