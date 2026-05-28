"""按群禁用插件（默认可用域=全群）；JSON 持久化（nonebot_plugin_localstore）。"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from functools import wraps
from json import JSONDecodeError, loads
from pathlib import Path
from typing import Any
from collections.abc import Awaitable, Callable, Iterable

from nonebot.internal.adapter import Bot, Event
from nonebot.internal.matcher import Matcher
from nonebot.log import logger

from src.plugins.platform_adapter.context import get_group_id, get_user_id

_RUN_PATCH_FLAG = "_dreamrain_perm_run_patched"
_STORE_VERSION = 3
_STORE_NAME = "permissions.json"
_ORIGINAL_MATCHER_RUN: Callable[..., Awaitable[Any]] | None = None


def _store_path() -> Path:
    from nonebot import require

    require("nonebot_plugin_localstore")
    from nonebot_plugin_localstore import get_data_file

    return get_data_file("permission_admin", _STORE_NAME)


def normalize_group_whitelist(value: Any) -> set[int]:
    """供其它插件配置解析用（如 priconne），与 permission_admin 禁用列表无关。"""
    if value in (None, ""):
        return set()

    if isinstance(value, str):
        text = value.strip()
        if not text:
            return set()
        if text.startswith("["):
            try:
                value = loads(text)
            except JSONDecodeError:
                value = [item.strip() for item in text.strip("[]").split(",") if item.strip()]
        else:
            value = [item.strip() for item in text.split(",") if item.strip()]

    if isinstance(value, (tuple, set)):
        value = list(value)

    if isinstance(value, list):
        return {int(item) for item in value if str(item).strip()}

    return {int(value)}


def _group_id_from_event(event: Event) -> int | None:
    return get_group_id(event)


def is_group_event_allowed(event: Event, whitelist: Iterable[int], *, allow_private: bool = True) -> bool:
    group_whitelist = whitelist if isinstance(whitelist, set) else normalize_group_whitelist(list(whitelist))
    return _is_group_allowed(event, group_whitelist, allow_private=allow_private)


def _is_group_allowed(event: Event, whitelist: set[int], *, allow_private: bool = True) -> bool:
    if not whitelist:
        return True
    gid = _group_id_from_event(event)
    if gid is None:
        return allow_private
    return gid in whitelist


@dataclass
class _PluginEntry:
    """在某插件下已禁用的群号、用户，以及 matcher 级最低特权等级。"""

    blocked_groups: set[int] = field(default_factory=set)
    blocked_users: set[int] = field(default_factory=set)
    matcher_levels: dict[str, int] = field(default_factory=dict)


class PermissionManager:
    """按 plugin id 记录「在哪些群禁用」。未出现在表中的插件 = 全群可用。"""

    __slots__ = ("_lock", "_by_plugin", "_global_blacklist", "_global_whitelist")

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._by_plugin: dict[str, _PluginEntry] = {}
        self._global_blacklist: set[int] = set()
        self._global_whitelist: set[int] = set()

    def _snapshot_for_json(self) -> dict[str, Any]:
        plugins: dict[str, Any] = {}
        for pid, e in self._by_plugin.items():
            if not e.blocked_groups and not e.blocked_users and not e.matcher_levels:
                continue
            entry: dict[str, Any] = {}
            if e.blocked_groups:
                entry["blocked_groups"] = sorted(e.blocked_groups)
            if e.blocked_users:
                entry["blocked_users"] = sorted(e.blocked_users)
            if e.matcher_levels:
                entry["matcher_levels"] = dict(sorted(e.matcher_levels.items()))
            plugins[pid] = entry
        result: dict[str, Any] = {"version": _STORE_VERSION, "plugins": plugins}
        result["global"] = {
            "blacklist": sorted(self._global_blacklist),
            "whitelist": sorted(self._global_whitelist),
        }
        return result

    def _persist_to_disk(self) -> None:
        with self._lock:
            payload = self._snapshot_for_json()
        try:
            path = _store_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            text = json.dumps(payload, ensure_ascii=False, indent=2)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(text, encoding="utf-8")
            tmp.replace(path)
        except OSError as e:
            logger.opt(exception=e).warning("permission_admin 持久化写入失败")

    def load_from_disk(self) -> None:
        path = _store_path()
        if not path.is_file():
            return
        try:
            raw = path.read_text(encoding="utf-8")
            data = json.loads(raw)
        except (OSError, JSONDecodeError) as e:
            logger.opt(exception=e).warning("permission_admin 持久化读取失败，已跳过")
            return

        plugins = data.get("plugins")
        global_section = data.get("global")

        with self._lock:
            self._by_plugin.clear()
            self._global_blacklist.clear()
            self._global_whitelist.clear()

            if isinstance(global_section, dict):
                bl = global_section.get("blacklist", [])
                if isinstance(bl, list):
                    self._global_blacklist = {int(x) for x in bl}
                wl = global_section.get("whitelist", [])
                if isinstance(wl, list):
                    self._global_whitelist = {int(x) for x in wl}

            if isinstance(plugins, dict):
                for pid, row in plugins.items():
                    if not isinstance(pid, str) or not isinstance(row, dict):
                        continue
                    try:
                        blocked: set[int] = set()
                        blocked_users: set[int] = set()
                        matcher_levels: dict[str, int] = {}
                        if "blocked_groups" in row:
                            bg = row.get("blocked_groups", [])
                            if isinstance(bg, list):
                                blocked = {int(x) for x in bg}
                        if "blocked_users" in row:
                            bu = row.get("blocked_users", [])
                            if isinstance(bu, list):
                                blocked_users = {int(x) for x in bu}
                        if "matcher_levels" in row:
                            ml = row.get("matcher_levels", {})
                            if isinstance(ml, dict):
                                matcher_levels = {
                                    str(k): int(v)
                                    for k, v in ml.items()
                                    if isinstance(v, (int, float))
                                }
                        if "group_whitelist" in row and row.get("group_whitelist") is not None:
                            logger.warning(
                                "permission_admin: 已忽略旧版 group_whitelist（%s），"
                                "请用「群内 perm off」按群禁用",
                                pid,
                            )
                        if not blocked and not blocked_users and not matcher_levels:
                            continue
                        self._by_plugin[pid] = _PluginEntry(
                            blocked_groups=blocked,
                            blocked_users=blocked_users,
                            matcher_levels=matcher_levels,
                        )
                    except (TypeError, ValueError):
                        logger.warning(f"permission_admin 跳过损坏的插件记录: {pid!r}")

    def block_in_group(self, plugin_id: str, group_id: int) -> None:
        with self._lock:
            entry = self._by_plugin.get(plugin_id) or _PluginEntry()
            entry.blocked_groups.add(int(group_id))
            self._by_plugin[plugin_id] = entry
        self._persist_to_disk()

    def unblock_in_group(self, plugin_id: str, group_id: int) -> None:
        with self._lock:
            entry = self._by_plugin.get(plugin_id)
            if entry is None:
                return
            entry.blocked_groups.discard(int(group_id))
            if not entry.blocked_groups and not entry.blocked_users and not entry.matcher_levels:
                self._by_plugin.pop(plugin_id, None)
        self._persist_to_disk()

    def block_user(self, plugin_id: str, user_id: int) -> None:
        with self._lock:
            entry = self._by_plugin.get(plugin_id) or _PluginEntry()
            entry.blocked_users.add(int(user_id))
            self._by_plugin[plugin_id] = entry
        self._persist_to_disk()

    def unblock_user(self, plugin_id: str, user_id: int) -> None:
        with self._lock:
            entry = self._by_plugin.get(plugin_id)
            if entry is None:
                return
            entry.blocked_users.discard(int(user_id))
            if not entry.blocked_groups and not entry.blocked_users and not entry.matcher_levels:
                self._by_plugin.pop(plugin_id, None)
        self._persist_to_disk()

    def clear_blocks(self, plugin_id: str) -> None:
        """清除该插件所有群和用户的禁用记录（保留 matcher 等级配置）。"""
        with self._lock:
            entry = self._by_plugin.get(plugin_id)
            if entry is None:
                return
            entry.blocked_groups.clear()
            entry.blocked_users.clear()
            if not entry.matcher_levels:
                self._by_plugin.pop(plugin_id, None)
        self._persist_to_disk()

    # ── matcher 等级 ──────────────────────────────────────────

    def set_matcher_level(self, plugin_id: str, handler_name: str, level: int) -> None:
        with self._lock:
            entry = self._by_plugin.get(plugin_id) or _PluginEntry()
            entry.matcher_levels[handler_name] = int(level)
            self._by_plugin[plugin_id] = entry
        self._persist_to_disk()

    def reset_matcher_level(self, plugin_id: str, handler_name: str) -> None:
        with self._lock:
            entry = self._by_plugin.get(plugin_id)
            if entry is None:
                return
            entry.matcher_levels.pop(handler_name, None)
            if not entry.blocked_groups and not entry.blocked_users and not entry.matcher_levels:
                self._by_plugin.pop(plugin_id, None)
        self._persist_to_disk()

    def get_matcher_levels(self, plugin_id: str) -> dict[str, int]:
        with self._lock:
            entry = self._by_plugin.get(plugin_id)
            if entry is None or not entry.matcher_levels:
                return {}
            return dict(entry.matcher_levels)

    # ── 全局黑/白名单 ─────────────────────────────────────────

    def add_to_blacklist(self, user_id: int) -> None:
        with self._lock:
            self._global_blacklist.add(int(user_id))
        self._persist_to_disk()

    def remove_from_blacklist(self, user_id: int) -> None:
        with self._lock:
            self._global_blacklist.discard(int(user_id))
        self._persist_to_disk()

    def add_to_whitelist(self, user_id: int) -> None:
        with self._lock:
            self._global_whitelist.add(int(user_id))
        self._persist_to_disk()

    def remove_from_whitelist(self, user_id: int) -> None:
        with self._lock:
            self._global_whitelist.discard(int(user_id))
        self._persist_to_disk()

    def get_blacklist(self) -> list[int]:
        with self._lock:
            return sorted(self._global_blacklist)

    def get_whitelist(self) -> list[int]:
        with self._lock:
            return sorted(self._global_whitelist)

    def get_snapshot(self, plugin_id: str) -> dict[str, Any] | None:
        with self._lock:
            e = self._by_plugin.get(plugin_id)
            if e is None or (
                not e.blocked_groups
                and not e.blocked_users
                and not e.matcher_levels
            ):
                return None
            result: dict[str, Any] = {}
            if e.blocked_groups:
                result["blocked_groups"] = sorted(e.blocked_groups)
            if e.blocked_users:
                result["blocked_users"] = sorted(e.blocked_users)
            if e.matcher_levels:
                result["matcher_levels"] = dict(sorted(e.matcher_levels.items()))
            return result

    def list_loaded_plugins_for_group(self, group_id: int) -> list[dict[str, Any]]:
        """各已加载插件在指定群是否可用（未在 blocked 中即为可用）。

        仅列出注册了 Matcher 的插件，纯工具/基础设施插件不显示。
        """
        from nonebot.matcher import matchers
        from nonebot.plugin import get_loaded_plugins

        with_matchers: set[str] = set()
        for priority_list in matchers.values():
            for m in priority_list:
                pid = getattr(m, "plugin_id", None)
                if pid:
                    with_matchers.add(pid)

        loaded_ids = sorted(
            {p.id_ for p in get_loaded_plugins() if p.id_ in with_matchers}
        )
        gid = int(group_id)
        with self._lock:
            by = dict(self._by_plugin)
        rows: list[dict[str, Any]] = []
        for pid in loaded_ids:
            e = by.get(pid)
            blocked = e.blocked_groups if e else set()
            rows.append(
                {
                    "plugin_id": pid,
                    "available": gid not in blocked,
                }
            )
        return rows

    def _eval_plugin(self, plugin_id: str, event: Event) -> bool:
        entry = self._by_plugin.get(plugin_id)
        if entry is None:
            return True
        if entry.blocked_users:
            uid = get_user_id(event)
            if uid is not None and uid in entry.blocked_users:
                return False
        if entry.blocked_groups:
            gid = _group_id_from_event(event)
            if gid is not None and gid in entry.blocked_groups:
                return False
        return True

    async def is_event_allowed(self, plugin_id: str | None, bot: Bot, event: Event) -> bool:
        if not plugin_id:
            return True
        # 本插件的 perm 已带 SUPERUSER 权限；此处不再对超管全局放行，否则「perm off」后用超管测会一直能触发其它插件
        if plugin_id == "permission_admin":
            return True
        with self._lock:
            return self._eval_plugin(plugin_id, event)

    def is_plugin_domain_available(self, plugin_id: str, event: Event) -> bool:
        """当前事件上下文中插件是否可用（不含 SUPERUSER）。"""
        with self._lock:
            return self._eval_plugin(plugin_id, event)

    def reload_from_disk(self) -> dict[str, Any]:
        """从磁盘重新加载权限表，返回加载摘要。"""
        before = set(self._by_plugin.keys())
        self.load_from_disk()
        after = set(self._by_plugin.keys())
        return {
            "loaded_plugins": len(after),
            "added": sorted(after - before),
            "removed": sorted(before - after),
        }

    def is_plugin_loaded(self, plugin_id: str) -> bool:
        """检查 plugin_id 是否对应一个已加载的插件。"""
        from nonebot.plugin import get_loaded_plugins

        return plugin_id in {p.id_ for p in get_loaded_plugins()}


_manager = PermissionManager()


def get_permission_manager() -> PermissionManager:
    return _manager


def load_permission_store() -> None:
    """启动时从 JSON 加载按群禁用表（仅含 blocked_groups 非空的插件）。"""
    get_permission_manager().load_from_disk()


async def _patched_matcher_run(
    self: Matcher,
    bot: Bot,
    event: Event,
    state: Any,
    stack: Any = None,
    dependency_cache: Any = None,
) -> Any:
    plugin_id = self.__class__.plugin_id
    mgr = get_permission_manager()

    if not await mgr.is_event_allowed(plugin_id, bot, event):
        return

    # 全局黑名单 / SUPERUSER 放行 / matcher 等级检查
    if plugin_id and plugin_id != "permission_admin":
        from .privilege import PrivilegeLevel, resolve_user_level

        user_level = resolve_user_level(event, mgr, bot)

        # 1. 全局黑名单
        if user_level == PrivilegeLevel.BLACK:
            return

        # 2. SUPERUSER 跳过 matcher 等级检查
        if user_level == PrivilegeLevel.SUPERUSER:
            pass
        else:
            # 3. matcher 等级检查：取所有 handler 中配置的最高等级
            handler_names = [h.call.__name__ for h in self.handlers]  # type: ignore[union-attr]
            matcher_levels = mgr.get_matcher_levels(plugin_id)
            required = 0
            for name in handler_names:
                lvl = matcher_levels.get(name)
                if lvl is not None and lvl > required:
                    required = lvl
            if required > 0 and user_level < required:
                return

    if _ORIGINAL_MATCHER_RUN is None:
        raise RuntimeError("permission_admin matcher run patch not initialized")

    return await _ORIGINAL_MATCHER_RUN(
        self,
        bot,
        event,
        state,
        stack,
        dependency_cache,
    )


def install_global_matcher_guard() -> None:
    global _ORIGINAL_MATCHER_RUN

    if getattr(Matcher, _RUN_PATCH_FLAG, False):
        return

    _ORIGINAL_MATCHER_RUN = Matcher.run
    Matcher.run = _patched_matcher_run
    setattr(Matcher, _RUN_PATCH_FLAG, True)


def require_group_whitelist(whitelist: Iterable[int]):
    """已废弃。"""

    def decorator(func: Callable[..., Awaitable[Any]]):
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any):
            return await func(*args, **kwargs)

        return wrapper

    return decorator
