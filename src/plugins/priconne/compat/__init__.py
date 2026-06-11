from __future__ import annotations

from typing import Any, Iterable
import re

from nonebot import get_bot, get_driver, logger, require
from nonebot.adapters.onebot.v11 import Bot, MessageEvent, NoticeEvent
from nonebot.matcher import Matcher
from nonebot.plugin import on_message, on_notice
from nonebot.rule import Rule
from nonebot.typing import T_State

from src.plugins.platform_adapter.context import PlatformContext
from src.plugins.platform_adapter.message import Message, MessageSegment, coerce_message, prepend_at
from src.plugins.platform_adapter.sender import send_group, send_private, send_to_event

from . import aiorequests

require("nonebot_plugin_apscheduler")

try:
    from nonebot_plugin_apscheduler import scheduler
except Exception:
    scheduler = None


def on_startup(func):
    get_driver().on_startup(func)
    return func


def _flatten_patterns(items: Iterable[Any]) -> list[str]:
    result: list[str] = []
    for item in items:
        if isinstance(item, (tuple, list, set)):
            result.extend(str(x) for x in item)
        else:
            result.append(str(item))
    return result


def _strip_prefix_message(message: Message, prefix: str) -> Message:
    copied = Message(message)
    if copied and copied[0].type == "text":
        text = copied[0].data.get("text", "")
        if text.startswith(prefix):
            copied[0].data["text"] = text[len(prefix) :].lstrip()
            return copied
    return Message(str(message).replace(prefix, "", 1).lstrip())


class LegacyEvent:
    def __init__(
        self,
        event: MessageEvent | NoticeEvent,
        *,
        message: Message | None = None,
        raw_message: str | None = None,
        prefix: str | None = None,
        match: re.Match[str] | None = None,
    ):
        self._event = event
        self.message = message if message is not None else getattr(event, "message", Message())
        self.raw_message = raw_message if raw_message is not None else str(self.message)
        self.prefix = prefix
        self.platform = PlatformContext.from_event(event).platform
        self._extras = {
            "message": self.message,
            "raw_message": self.raw_message,
            "match": match,
        }

    def __getattr__(self, item):
        return getattr(self._event, item)

    def __getitem__(self, item):
        if item in self._extras:
            return self._extras[item]
        return getattr(self._event, item)

    def __setitem__(self, key, value):
        self._extras[key] = value


class LegacyBot:
    def __init__(self, bot: Bot, matcher: Matcher):
        self._bot = bot
        self._matcher = matcher

    async def send(self, ev: LegacyEvent, message: Any, at_sender: bool = False):
        return await send_to_event(self._bot, ev._event, message, at_sender=at_sender)

    async def finish(self, ev: LegacyEvent, message: Any, at_sender: bool = False):
        msg = prepend_at(message, getattr(ev, "user_id", None) if at_sender else None)
        await self._matcher.finish(msg)

    async def send_private_msg(self, **kwargs):
        return await send_private(self._bot, kwargs["user_id"], kwargs.get("message"))

    async def send_group_msg(self, **kwargs):
        group_id = kwargs.pop("group_id")
        message = kwargs.pop("message", None)
        return await send_group(self._bot, group_id, message, **kwargs)

    async def get_group_member_info(self, **kwargs):
        return await self._bot.get_group_member_info(**kwargs)


class LegacySession:
    def __init__(
        self,
        bot: Bot,
        matcher: Matcher,
        event: MessageEvent | NoticeEvent,
        *,
        current_arg_text: str = "",
        match: re.Match[str] | None = None,
    ):
        message = getattr(event, "message", Message())
        self.bot = bot
        self.matcher = matcher
        self.event = event
        self.current_arg_text = current_arg_text
        self.platform = PlatformContext.from_event(event, bot).platform
        self.ctx = {
            "user_id": getattr(event, "user_id", None),
            "group_id": getattr(event, "group_id", None),
            "message": message,
            "raw_message": str(message),
            "match": match,
        }

    async def send(self, message: Any):
        return await send_to_event(self.bot, self.event, message)

    async def finish(self, message: Any):
        await self.matcher.finish(coerce_message(message))


class _Priv:
    ADMIN = "admin"

    @staticmethod
    def check_priv(ev: LegacyEvent, level: str):
        if level != _Priv.ADMIN:
            return False
        sender = getattr(ev, "sender", None)
        role = getattr(sender, "role", None) if sender is not None else None
        return role in {"admin", "owner"}


priv = _Priv()


class Service:
    def __init__(self, name: str, **kwargs):
        self.name = name
        self.help_ = kwargs.get("help_", "")
        self.visible = kwargs.get("visible", True)
        self.enable_on_default = kwargs.get("enable_on_default", True)

    def _message_decorator(self, rule_factory, session_mode: bool = False):
        matcher = on_message(priority=5, block=False, rule=Rule(rule_factory))

        def decorator(func):
            @matcher.handle()
            async def _handle(bot: Bot, event: MessageEvent, matcher: Matcher, state: T_State):
                if session_mode:
                    session = LegacySession(
                        bot,
                        matcher,
                        event,
                        current_arg_text=state.get("legacy_current_arg_text", ""),
                        match=state.get("legacy_match"),
                    )
                    await func(session)
                    return

                legacy_event = LegacyEvent(
                    event,
                    message=state.get("legacy_message"),
                    raw_message=state.get("legacy_raw_message"),
                    prefix=state.get("legacy_prefix"),
                    match=state.get("legacy_match"),
                )
                await func(LegacyBot(bot, matcher), legacy_event)

            return func

        return decorator

    def on_fullmatch(self, *patterns, only_to_me: bool = False, **kwargs):
        fullmatches = _flatten_patterns(patterns)

        async def rule_factory(event: MessageEvent, state: T_State):
            if only_to_me and not getattr(event, "to_me", False):
                return False
            return event.get_plaintext().strip() in fullmatches

        return self._message_decorator(rule_factory)

    def on_prefix(self, *prefixes, only_to_me: bool = False, **kwargs):
        prefix_list = sorted(_flatten_patterns(prefixes), key=len, reverse=True)

        async def rule_factory(event: MessageEvent, state: T_State):
            if only_to_me and not getattr(event, "to_me", False):
                return False
            plain = event.get_plaintext().strip()
            for prefix in prefix_list:
                if plain.startswith(prefix):
                    message = _strip_prefix_message(event.message, prefix)
                    state["legacy_prefix"] = prefix
                    state["legacy_message"] = message
                    state["legacy_raw_message"] = str(message)
                    return True
            return False

        return self._message_decorator(rule_factory)

    def on_rex(self, pattern: str, only_to_me: bool = False, **kwargs):
        regex = re.compile(pattern)

        async def rule_factory(event: MessageEvent, state: T_State):
            if only_to_me and not getattr(event, "to_me", False):
                return False
            match = regex.match(event.get_plaintext().strip())
            if match is None:
                return False
            state["legacy_match"] = match
            return True

        return self._message_decorator(rule_factory)

    def on_command(self, command: str, aliases=(), only_to_me: bool = False, **kwargs):
        commands = sorted([command, *aliases], key=len, reverse=True)

        async def rule_factory(event: MessageEvent, state: T_State):
            if only_to_me and not getattr(event, "to_me", False):
                return False
            plain = event.get_plaintext().strip()
            for item in commands:
                if plain == item:
                    state["legacy_current_arg_text"] = ""
                    return True
                if plain.startswith(f"{item} "):
                    state["legacy_current_arg_text"] = plain[len(item) :].strip()
                    return True
            return False

        return self._message_decorator(rule_factory, session_mode=True)

    def on_message(self, rule=None):
        """匹配所有消息，可选额外 rule(event, state) -> bool"""

        async def rule_factory(event: MessageEvent, state: T_State):
            if rule is not None:
                from asyncio import iscoroutinefunction
                if iscoroutinefunction(rule):
                    return await rule(event, state)
                return rule(event, state)
            return True

        return self._message_decorator(rule_factory)

    def on_notice(self, notice_type: str, **kwargs):
        async def rule_factory(event: NoticeEvent, state: T_State):
            return getattr(event, "notice_type", None) == notice_type

        matcher = on_notice(priority=5, block=False, rule=Rule(rule_factory))

        def decorator(func):
            @matcher.handle()
            async def _handle(bot: Bot, event: NoticeEvent, matcher: Matcher, state: T_State):
                session = LegacySession(
                    bot,
                    matcher,
                    event,
                    match=state.get("legacy_match"),
                )
                await func(session)

            return func

        return decorator

    def scheduled_job(self, *args, **kwargs):
        if scheduler is None:
            def passthrough(func):
                logger.warning("nonebot_plugin_apscheduler unavailable, skip scheduled job {}", func.__name__)
                return func

            return passthrough
        return scheduler.scheduled_job(*args, **kwargs)


__all__ = [
    "Service",
    "aiorequests",
    "get_bot",
    "logger",
    "on_startup",
    "priv",
]
