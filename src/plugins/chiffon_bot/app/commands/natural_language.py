"""Cross-game natural-language song query."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import timedelta
import re

from nonebot import on_message
from nonebot.adapters import Bot, Event
from nonebot.internal.matcher import Matcher
from nonebot.log import logger
from nonebot.params import EventPlainText
from nonebot.rule import Rule

from ._reaction import ack_message

from ...shared.bot_response import BotResponse
from ...shared.game.adapter import DomainAdapter
from ...shared.game.registry import iter_searchable_adapters
from ...shared.handlers.generic_song_info import generic_song_info
from ...shared.search.song_query import MatchType, SongQueryResult, search_song
from ._response import finish_with, send_with

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
    results = await search_song(query, game_code=adapter.game_code)
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
    text = choice_text.strip().lower()
    if not text:
        return None

    if text.isdigit():
        index = int(text)
        if 1 <= index <= len(hits):
            return hits[index - 1]
        return None

    matches = [hit for hit in hits if text in _choice_tokens(hit.adapter)]
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
) -> tuple[asyncio.Future[str], type[Matcher]]:
    future: asyncio.Future[str] = asyncio.get_running_loop().create_future()

    async def is_same_conversation(event: Event) -> bool:
        return event.get_user_id() == user_id and event.get_session_id() == session_id

    choice_matcher = on_message(
        rule=Rule(is_same_conversation),
        priority=1,
        block=True,
        expire_time=timedelta(seconds=timeout_seconds),
    )

    @choice_matcher.handle()
    async def handle_choice(event: Event):
        if not future.done():
            future.set_result(event.get_plaintext().strip())
        await choice_matcher.finish()

    return future, choice_matcher


async def _wait_for_adapter_choice(
    *,
    event: Event,
    hits: list[_SearchHit],
    timeout_seconds: int = _DISAMBIGUATION_TIMEOUT_SECONDS,
) -> _SearchHit | None:
    future, matcher = _register_choice_waiter(
        user_id=event.get_user_id(),
        session_id=event.get_session_id(),
        timeout_seconds=timeout_seconds,
    )
    try:
        try:
            choice_text = await asyncio.wait_for(future, timeout=timeout_seconds)
        except asyncio.TimeoutError:
            return None
        return _resolve_adapter_choice(choice_text, hits)
    finally:
        _destroy_matcher(matcher)


def register_natural_language_commands() -> None:
    song_query_handler = on_message(priority=10, block=False)

    @song_query_handler.handle()
    async def handle_cross_game_song_query(
        bot: Bot,
        event: Event,
        plain_text: str = EventPlainText(),
    ):
        text = plain_text.strip()
        song_query = _extract_song_query(text)

        if not song_query or not (1 <= len(song_query) <= 50):
            return

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
        await send_with(_build_conflict_message(song_query, best_hits, message_id))
        selected = await _wait_for_adapter_choice(event=event, hits=best_hits)
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
