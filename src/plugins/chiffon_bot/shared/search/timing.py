"""DEBUG timings for live message dispatch and search stages."""

from contextlib import contextmanager
from time import perf_counter

from nonebot import logger
from nonebot.adapters import Event
from nonebot.matcher import Matcher, current_event
from nonebot.message import event_preprocessor, run_preprocessor, run_postprocessor
from nonebot.typing import T_State


@contextmanager
def stage(name: str):
    start = perf_counter()
    try:
        yield
    finally:
        try:
            event = current_event.get()
        except LookupError:
            event = None
        logger.debug("[search timing] event={} stage={} elapsed={:.4f}s",
                     getattr(event, "message_id", "-"), name, perf_counter() - start)


@event_preprocessor
async def received(event: Event, state: T_State):
    if event.get_type() == "message":
        state["_chiffon_received_at"] = perf_counter()


@run_preprocessor
async def matcher_started(matcher: Matcher, event: Event, state: T_State):
    if not (matcher.module_name or "").startswith("src.plugins.chiffon_bot"):
        return
    now = perf_counter()
    state["_chiffon_matcher_at"] = now
    logger.debug("[search timing] event={} matcher={} dispatch_wait={:.4f}s",
                 getattr(event, "message_id", "-"), matcher.module_name,
                 now - state.get("_chiffon_received_at", now))


@run_postprocessor
async def matcher_finished(matcher: Matcher, event: Event, state: T_State):
    start = state.get("_chiffon_matcher_at")
    if start is not None:
        logger.debug("[search timing] event={} matcher={} handler={:.4f}s",
                     getattr(event, "message_id", "-"), matcher.module_name, perf_counter() - start)
