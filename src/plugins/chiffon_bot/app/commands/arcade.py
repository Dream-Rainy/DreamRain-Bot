"""Generic arcade-songs catalog commands."""

from __future__ import annotations

from typing import Any

from nonebot.adapters import Event, Message
from nonebot.params import CommandArg

from arcade_helper.search import MatchType, SongQueryResult

from ...integrations.lxns.client import lxns_client
from ...shared.bot_response import BotResponse
from ...shared.handlers.song_text import format_song_text_detail, load_song_jacket_bytes
from ...shared.search.catalog_search import search_song_with_audit
from ...shared.search.timing import stage
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
        with stage("song.search"):
            results = await search_song_with_audit(query, game_code=game_code)
    except Exception as e:  # noqa: BLE001
        return BotResponse(text=f"查询 {game_code} 曲库失败: {e}", reply_to=message_id)
    try:
        with stage("song.sites"):
            sites = await lxns_client.data.catalog.arcade_songs.sites()
    except Exception:  # noqa: BLE001
        sites = []
    return await build_arcade_song_response(game_code, results, message_id, arcade_sites=sites)


async def query_arcade_game_list(message_id: int) -> BotResponse:
    try:
        sites = await lxns_client.data.catalog.arcade_songs.sites()
    except Exception as e:  # noqa: BLE001
        return BotResponse(text=f"获取 arcade-songs 游戏列表失败: {e}", reply_to=message_id)

    game_codes = _arcade_game_codes(sites)
    if not game_codes:
        return BotResponse(text="arcade-songs 没有可查询的游戏", reply_to=message_id)
    lines = [f"arcade-songs 可查询游戏（{len(game_codes)} 个）："]
    lines.extend(f"[{game_code}]" for game_code in game_codes)
    return BotResponse(text="\n".join(lines), reply_to=message_id)


async def query_arcade_song_games(query: str, message_id: int) -> BotResponse:
    try:
        resolution = await lxns_client.catalog.search_all(query)
        exact = [c for c in resolution.candidates
                 if c.match_type in {"exact_title", "exact_alias"}]
        if exact:
            from arcade_helper.storage.tortoise.catalog_models import GameSong
            # Expand only confirmed work identities; equal titles do not establish identity.
            rows = await GameSong.filter(work_id__in={c.work_id for c in exact}, active=True).only(
                "id", "work_id", "game_code", "title"
            ).order_by("game_code", "id")
            public_ids = await lxns_client.catalog.public_song_ids([(song.game_code, song.id) for song in rows])
            lines = [f"《{query}》在 {len({s.game_code for s in rows})} 个游戏中找到，共 {len(rows)} 条曲目记录："]
            work_numbers = {work_id: index for index, work_id in enumerate(dict.fromkeys(str(song.work_id) for song in rows), start=1)}
            ambiguous = len(work_numbers) > 1
            if ambiguous:
                lines.append("存在多个同名作品，以下结果按作品标注：")
            for song in rows:
                song_id = public_ids[(song.game_code, song.id)]
                suffix = f"（作品 {work_numbers[str(song.work_id)]}）" if ambiguous else ""
                lines.append(f"[{song.game_code}] [{song_id}] {song.title}{suffix}")
        elif resolution.candidates:
            lines = [f"未找到《{query}》的精确匹配，以下是近似结果："]
            candidates = sorted(resolution.candidates, key=lambda c: c.score, reverse=True)[:10]
            public_ids = await lxns_client.catalog.public_song_ids([(c.game_code, c.game_song_id) for c in candidates])
            for candidate in candidates:
                song_id = public_ids[(candidate.game_code, candidate.game_song_id)]
                lines.append(f"[{candidate.game_code}] [{song_id}] {candidate.title} ({candidate.score:.0f}%)")
        else:
            lines = [f"未在已导入曲库中找到《{query}》；管理员可用 /admin.alias sync <game> 导入曲库。"]
        return BotResponse(text="\n".join(lines), reply_to=message_id)
    except Exception as exc:
        return BotResponse(text=f"跨游戏曲库查询失败：{exc}", reply_to=message_id)


async def query_arcade_artist(game_code: str, artist: str, message_id: int) -> BotResponse:
    gc, query = game_code.strip().lower(), artist.strip()
    if not gc or not query:
        return BotResponse(text="用法：/arcade.artist <game_code> <曲师名>", reply_to=message_id)
    try:
        songs = await lxns_client.catalog.load_search_songs(gc)
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

    perfect = [result for result in results if result.match_type.value.startswith("exact_")]
    if len(perfect) > 1 or (not perfect and len(results) > 1):
        lines = [f"[{game_code}] 找到多个结果，请使用明确的歌曲 ID 查询：", ""]
        for result in results[:5]:
            artist = _get_text(result.song_data, "artist")
            suffix = f"  {artist}" if artist else ""
            song_id = f"catalog:{result.song_id}" if getattr(result.song_data, "catalog_only", False) else result.song_id
            lines.append(f"[{song_id}] {result.title}{suffix} ({result.match_score:.0f}%)")
        if len(results) > 5:
            lines.append(f"...还有 {len(results) - 5} 个结果")
        return BotResponse(text="\n".join(lines), reply_to=message_id)

    result = perfect[0] if perfect else results[0]
    with stage("song.jacket"):
        image = await load_song_jacket_bytes(game_code, result, arcade_sites=arcade_sites)
    return BotResponse(
        text="\n".join(format_song_text_detail(game_code, result)),
        image=image,
        reply_to=message_id,
    )


def register_arcade_commands(group) -> None:
    help_cmd = group.command("help")

    @help_cmd.handle()
    async def _help(event: Event):
        await finish_with(BotResponse(
            text=(
                "🎮 支持的游戏与功能\n\n"
                "maimai：查歌、别名、随机选曲、曲绘识别、\n"
                "B50/R50、玩家资料、趋势图\n"
                "CHUNITHM：查歌、别名、随机选曲\n"
                "其他音游：查歌、曲师查询、别名、跨游戏查询\n\n"
                "游戏列表：/arcade.list\n"
                "详细用法：/mai.help、/chuni.help\n"
                "通用查歌：/arcade.song <游戏> <歌曲名或ID>\n"
                "曲师查询：/arcade.artist <游戏> <曲师名>\n"
                "别名查询：/arcade.alias <游戏> <歌曲名或ID>\n"
                "跨游戏查询：/arcade.games <歌曲名>\n"
                "账号管理：/acc help\n"
                "活动功能：/event.help\n\n"
                "其他音游需先导入曲库；管理员（SUPERUSER）使用\n"
                "/admin.alias sync <游戏>。"
            ),
            reply_to=event.message_id,
        ))

    list_cmd = group.command("list")

    @list_cmd.handle()
    async def _list(event: Event):
        await finish_with(await query_arcade_game_list(event.message_id))

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


def _arcade_game_codes(sites: list[dict]) -> list[str]:
    return [
        code
        for code in dict.fromkeys(
            str(site.get("gameCode") or "").strip().lower()
            for site in sites
            if isinstance(site, dict)
        )
        if code and code != "any"
    ]


__all__ = [
    "build_arcade_song_response",
    "parse_arcade_song_args",
    "query_arcade_artist",
    "query_arcade_game_list",
    "query_arcade_song",
    "query_arcade_song_games",
    "register_arcade_commands",
]
