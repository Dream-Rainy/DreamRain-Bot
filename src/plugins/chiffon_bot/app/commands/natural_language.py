"""Cross-game natural-language song query."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import timedelta

from arcade_helper.search import MatchType, SongQueryResult
from nonebot import on_message
from nonebot.adapters import Bot, Event
from nonebot.internal.matcher import Matcher
from nonebot.log import logger
from nonebot.params import EventPlainText
from nonebot.rule import Rule

from ...integrations.lxns.client import lxns_client
from ...shared.bot_response import BotResponse
from ...shared.game.adapter import DomainAdapter
from ...shared.game.registry import iter_searchable_adapters
from ...shared.handlers.generic_song_info import generic_song_info
from ...shared.search.catalog_search import search_song_with_audit
from ._reaction import ack_message
from ._response import finish_with, send_with
from .arcade import query_arcade_artist, query_arcade_song, query_arcade_song_games

_DISAMBIGUATION_TIMEOUT_SECONDS = 30

_PRIORITY: dict[MatchType, int] = {
    MatchType.EXACT_ID: 0,
    MatchType.EXACT_TITLE: 1,
    MatchType.EXACT_ALIAS: 2,
    MatchType.FUZZY_TITLE: 3,
    MatchType.PINYIN_INITIALS: 3,
    MatchType.PINYIN_FULL: 3,
    MatchType.SIMPLIFIED: 3,
    MatchType.FUZZY_ALIAS: 4,
}

_SONG_PATTERNS = [
    r"^(.+?)是什么歌[？?]?$",
    r"^(.+?)是啥歌[？?]?$",
]

_ARCADE_SONG_PATTERN = r"^查歌\s+(\S+)\s+(.+)$"
_SONG_GAMES_PATTERNS = [
    r"^(.+?)在哪些游戏(?:里|中)[？?]?$",
    r"^哪些游戏有\s*(.+?)[？?]?$",
]
_ARTIST_SONGS_PATTERN = (
    r"^(.+?)\s*在\s*(\S+?)\s*"
    r"(?:游戏)?(?:里|中)有哪些(?:首)?(?:歌曲|歌)[？?]?$"
)


@dataclass(frozen=True)
class _SearchHit:
    adapter: DomainAdapter
    results: list[SongQueryResult]
    priority: int

    @property
    def best(self) -> SongQueryResult:
        return self.results[0]


def _best_priority(results: list[SongQueryResult]) -> int | None:
    if not results:
        return None
    return min(_PRIORITY.get(result.match_type, 99) for result in results)


async def _search_adapter(adapter: DomainAdapter, query: str) -> _SearchHit | None:
    results = await search_song_with_audit(query, game_code=adapter.game_code)
    priority = _best_priority(results)
    if priority is None:
        return None
    return _SearchHit(adapter=adapter, results=results, priority=priority)


def _extract_song_query(text: str) -> str | None:
    for pattern in _SONG_PATTERNS:
        match = re.match(pattern, text)
        if match:
            return match.group(1).strip()
    return None


def _extract_song_games_query(text: str) -> str | None:
    for pattern in _SONG_GAMES_PATTERNS:
        match = re.match(pattern, text, re.IGNORECASE)
        if match:
            query = match.group(1).strip().strip("《》「」『』“”\"'")
            if query:
                return query
    return None


def _extract_artist_songs_query(text: str) -> tuple[str, str] | None:
    match = re.match(_ARTIST_SONGS_PATTERN, text, re.IGNORECASE)
    if not match:
        return None
    artist, game_code = match.group(1).strip(), match.group(2).strip().lower()
    if not artist or not game_code:
        return None
    return game_code, artist


async def _known_arcade_song_codes() -> set[str] | None:
    """Fetch known arcade-songs game codes; ``None`` disables code filtering."""
    try:
        sites = await lxns_client.data.catalog.arcade_songs.sites()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[NL] 获取 arcade-songs 站点列表失败，跳过游戏代码校验: {e}")
        return None
    return {
        str(site["gameCode"]).strip().lower()
        for site in sites
        if isinstance(site, dict) and site.get("gameCode")
    }


def _extract_arcade_song_query(
    text: str, valid_codes: set[str] | None = None
) -> tuple[str, str] | None:
    match = re.match(_ARCADE_SONG_PATTERN, text, re.IGNORECASE)
    if not match:
        return None
    game_code = match.group(1).strip().lower()
    query = match.group(2).strip()
    if not game_code or not query:
        return None
    if valid_codes is not None and game_code not in valid_codes:
        return None
    return game_code, query


def _build_conflict_message(
    query: str,
    hits: list[_SearchHit],
    message_id: int,
) -> BotResponse:
    lines = ["在多个游戏中找到匹配，请回复序号或游戏名："]

    for idx, hit in enumerate(hits, start=1):
        result = hit.best
        label = str(idx)
        lines.append(
            f"{label}. [{hit.adapter.display_name}] [{result.song_id}] {result.title}"
        )

    aliases = []
    for hit in hits:
        adapter_aliases = " / ".join(hit.adapter.select_aliases)
        aliases.append(f"{hit.adapter.display_name}: {adapter_aliases}")

    lines.extend(["", "可回复：" + "；".join(aliases)])
    return BotResponse(text="\n".join(lines), reply_to=message_id)


def _choice_tokens(adapter: DomainAdapter) -> set[str]:
    tokens = {
        adapter.game_code,
        adapter.command_prefix,
        adapter.display_name,
        *adapter.select_aliases,
    }
    return {token.strip().lower() for token in tokens if token and token.strip()}


def _resolve_adapter_choice(choice_text: str, hits: list[_SearchHit]) -> _SearchHit | None:
    game_code = _resolve_game_choice(choice_text, [hit.adapter.game_code for hit in hits])
    return next((hit for hit in hits if hit.adapter.game_code == game_code), None)


def _resolve_game_choice(choice_text: str, game_codes: list[str]) -> str | None:
    text = choice_text.strip().lower()
    if not text:
        return None

    if text.isdecimal():
        index = int(text)
        if 1 <= index <= len(game_codes):
            return game_codes[index - 1]
        return None

    adapters = {adapter.game_code: adapter for adapter in iter_searchable_adapters()}
    matches = [code for code in game_codes if text in (
        _choice_tokens(adapters[code]) if code in adapters else {code}
    )]
    if len(matches) == 1:
        return matches[0]
    return None


def _available_choice_text(hits: list[_SearchHit]) -> str:
    parts = []
    for idx, hit in enumerate(hits, start=1):
        aliases = " / ".join(hit.adapter.select_aliases)
        parts.append(f"{idx} 或 {aliases}")
    return "；".join(parts)


def _destroy_matcher(matcher: type[Matcher]) -> None:
    try:
        matcher.destroy()
    except ValueError:
        pass


def _register_choice_waiter(
    *,
    user_id: str,
    session_id: str,
    timeout_seconds: int,
    game_codes: list[str] | None = None,
) -> tuple[asyncio.Future[str], type[Matcher]]:
    future: asyncio.Future[str] = asyncio.get_running_loop().create_future()
    choice_tokens = {"取消", "cancel", *(game_codes or ())}
    for adapter in iter_searchable_adapters():
        if adapter.game_code in (game_codes or ()):
            choice_tokens.update(_choice_tokens(adapter))

    async def is_same_conversation(event: Event) -> bool:
        return not future.done() and event.get_user_id() == user_id and event.get_session_id() == session_id

    choice_matcher = on_message(
        rule=Rule(is_same_conversation),
        priority=1,
        block=False,
        expire_time=timedelta(seconds=timeout_seconds),
    )

    @choice_matcher.handle()
    async def handle_choice(event: Event, matcher: Matcher):
        if future.done():
            return
        text = event.get_plaintext().strip()
        if text.isdecimal() or text.lower() in choice_tokens:
            matcher.stop_propagation()
            future.set_result(text)
        else:
            # Cancel the old handler quietly while this message continues dispatching.
            future.cancel()
        _destroy_matcher(choice_matcher)
        await choice_matcher.finish()

    return future, choice_matcher


async def _wait_for_adapter_choice(
    *,
    event: Event,
    hits: list[_SearchHit],
    timeout_seconds: int = _DISAMBIGUATION_TIMEOUT_SECONDS,
    prompt: BotResponse | None = None,
) -> _SearchHit | None:
    game_code = await _wait_for_game_choice(
        event=event, game_codes=[hit.adapter.game_code for hit in hits],
        timeout_seconds=timeout_seconds, prompt=prompt,
    )
    return next((hit for hit in hits if hit.adapter.game_code == game_code), None)


async def _wait_for_game_choice(
    *,
    event: Event,
    game_codes: list[str],
    timeout_seconds: int = _DISAMBIGUATION_TIMEOUT_SECONDS,
    prompt: BotResponse | None = None,
) -> str | None:
    choice_text = await _wait_for_choice_text(
        event=event, game_codes=game_codes, timeout_seconds=timeout_seconds, prompt=prompt,
    )
    return _resolve_game_choice(choice_text, game_codes) if choice_text is not None else None


async def _wait_for_choice_text(
    *,
    event: Event,
    game_codes: list[str] | None = None,
    timeout_seconds: int = _DISAMBIGUATION_TIMEOUT_SECONDS,
    prompt: BotResponse | None = None,
) -> str | None:
    future, matcher = _register_choice_waiter(
        user_id=event.get_user_id(),
        session_id=event.get_session_id(),
        timeout_seconds=timeout_seconds,
        game_codes=game_codes,
    )
    try:
        if prompt is not None:
            await send_with(prompt)
        try:
            choice_text = await asyncio.wait_for(future, timeout=timeout_seconds)
        except asyncio.TimeoutError:
            return None
        return choice_text
    finally:
        if not future.done():
            future.cancel()
        _destroy_matcher(matcher)


async def _query_alias_song(song_query: str, event: Event) -> BotResponse:
    resolution = await lxns_client.catalog.search_all(song_query)
    candidates = resolution.candidates
    if not candidates:
        return BotResponse(text="未找到匹配的歌曲", reply_to=event.message_id)

    adapters = {adapter.game_code: adapter for adapter in iter_searchable_adapters()}
    preferred = [c for c in candidates if c.game_code == resolution.inferred_game]
    if len(preferred) == 1 and preferred[0].match_type.startswith("exact_"):
        candidates = preferred

    if len(candidates) > 1:
        groups = {}
        for candidate in candidates:
            groups.setdefault(candidate.work_id, []).append(candidate)
        choices = [candidate for matches in groups.values() for candidate in matches][:10]
        public_ids = await lxns_client.catalog.public_song_ids([
            (candidate.game_code, candidate.game_song_id) for candidate in choices
        ])
        lines = [f"找到 {len(groups)} 首匹配乐曲，请回复选项序号："]
        number = 0
        for matches in groups.values():
            visible = matches[:len(choices) - number]
            if not visible:
                break
            title = matches[0].title
            score = max(candidate.score for candidate in matches)
            suffix = "" if any(candidate.match_type.startswith("exact_") for candidate in matches) else f" ({score:.0f}%)"
            lines.append(title + suffix)
            options = []
            for candidate in visible:
                number += 1
                adapter = adapters.get(candidate.game_code)
                name = adapter.display_name if adapter else candidate.game_code
                song_id = public_ids[(candidate.game_code, candidate.game_song_id)]
                variant = f"（{candidate.title}）" if candidate.title != title else ""
                options.append(f"{number}. {name} [{song_id}]{variant}")
            lines.append("  " + " / ".join(options))
        if len(candidates) > len(choices):
            lines.append(f"还有 {len(candidates) - len(choices)} 个收录，请缩小查询范围后重试。")

        choice = await _wait_for_choice_text(
            event=event, prompt=BotResponse(text="\n".join(lines), reply_to=event.message_id),
            game_codes=list(dict.fromkeys(candidate.game_code for candidate in choices)),
        )
        if choice is None:
            return BotResponse(text="选曲超时，已取消。", reply_to=event.message_id)
        selected = None
        if choice.isdecimal():
            if 1 <= int(choice) <= len(choices):
                selected = choices[int(choice) - 1]
        else:
            game_code = _resolve_game_choice(choice, list(dict.fromkeys(c.game_code for c in choices)))
            matches = [candidate for candidate in candidates if candidate.game_code == game_code]
            if len(matches) == 1:
                selected = matches[0]
        if selected is None:
            return BotResponse(text="没有识别到唯一的歌曲选项，已取消。请重新查歌并回复列表序号。", reply_to=event.message_id)
        candidate = selected
        song_id = public_ids[(candidate.game_code, candidate.game_song_id)]
    else:
        candidate = candidates[0]
        song_id = await lxns_client.catalog.public_song_id(candidate.game_code, candidate.game_song_id)

    adapter = adapters.get(candidate.game_code)
    if adapter is not None:
        return await generic_song_info(song_id, event.get_user_id(), event.message_id, adapter)
    return await query_arcade_song(candidate.game_code, song_id, event.message_id)


def register_natural_language_commands() -> None:
    song_query_handler = on_message(priority=10, block=False)

    @song_query_handler.handle()
    async def handle_cross_game_song_query(
        bot: Bot,
        event: Event,
        plain_text: str = EventPlainText(),
    ):
        text = plain_text.strip()
        song_games_query = _extract_song_games_query(text)
        if song_games_query and len(song_games_query) <= 50:
            await ack_message(event, bot)
            logger.info(f"[NL] arcade-songs 游戏查询: {song_games_query!r}")
            await finish_with(
                await query_arcade_song_games(song_games_query, event.message_id)
            )

        artist_songs_query = _extract_artist_songs_query(text)
        if artist_songs_query is not None:
            game_code, artist = artist_songs_query
            if len(artist) <= 50:
                await ack_message(event, bot)
                logger.info(f"[NL] arcade-songs 曲师查询: {game_code} {artist!r}")
                await finish_with(
                    await query_arcade_artist(game_code, artist, event.message_id)
                )

        arcade_query = _extract_arcade_song_query(text)
        if arcade_query is not None:
            codes = await _known_arcade_song_codes()
            if codes is not None and arcade_query[0] not in codes:
                arcade_query = None
        if arcade_query is not None:
            game_code, query = arcade_query
            await ack_message(event, bot)
            logger.info(f"[NL] arcade-songs 查歌: {game_code} {query!r}")
            await finish_with(await query_arcade_song(game_code, query, event.message_id))

        song_query = _extract_song_query(text)

        if not song_query or not (1 <= len(song_query) <= 50):
            return

        if lxns_client.catalog.aliases_enabled:
            await ack_message(event, bot)
            try:
                response = await _query_alias_song(song_query, event)
            except Exception as exc:
                response = BotResponse(text=f"跨游戏查歌失败：{exc}", reply_to=event.message_id)
            await finish_with(response)

        adapters = iter_searchable_adapters()
        if not adapters:
            return

        await ack_message(event, bot)
        logger.info(f"[NL] 跨游戏查歌: {song_query!r}")
        raw_hits = await asyncio.gather(
            *(_search_adapter(adapter, song_query) for adapter in adapters)
        )
        hits = [hit for hit in raw_hits if hit is not None]

        user_id = event.get_user_id()
        message_id = event.message_id

        if not hits:
            await finish_with(BotResponse(text="未找到匹配的歌曲", reply_to=message_id))

        best_priority = min(hit.priority for hit in hits)
        best_hits = [hit for hit in hits if hit.priority == best_priority]

        if len(best_hits) == 1:
            hit = best_hits[0]
            logger.info(
                f"[NL] {hit.adapter.display_name} 命中 "
                f"(prio={hit.priority}): [{hit.best.song_id}] {hit.best.title}"
            )
            await finish_with(
                await generic_song_info(song_query, user_id, message_id, hit.adapter)
            )

        logger.info(
            "[NL] 同优先级冲突 "
            + " ".join(
                f"{hit.adapter.game_code}=[{hit.best.song_id}]{hit.best.title}"
                for hit in best_hits
            )
        )
        selected = await _wait_for_adapter_choice(
            event=event, hits=best_hits,
            prompt=_build_conflict_message(song_query, best_hits, message_id),
        )
        if selected is None:
            await finish_with(
                BotResponse(
                    text=(
                        "没有识别到要查询的游戏，已取消。\n"
                        f"可选：{_available_choice_text(best_hits)}"
                    ),
                    reply_to=message_id,
                )
            )

        logger.info(
            f"[NL] 用户选择 {selected.adapter.display_name}: "
            f"[{selected.best.song_id}] {selected.best.title}"
        )
        await finish_with(
            await generic_song_info(song_query, user_id, message_id, selected.adapter)
        )
