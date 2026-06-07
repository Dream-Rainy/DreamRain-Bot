from __future__ import annotations

import html
from functools import lru_cache
from io import BytesIO
from pathlib import Path
import re
from dataclasses import dataclass
from typing import Any, Callable, Coroutine, Iterable

import httpx
from nonebot import get_driver, get_plugin_config, logger, on_message
from nonebot.adapters import Bot as BaseBot, Event as BaseEvent
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message, MessageEvent, MessageSegment
from nonebot.matcher import Matcher
from nonebot.params import EventPlainText
from nonebot.permission import SUPERUSER
from nonebot.rule import Rule
from PIL import Image, ImageDraw, ImageFont

from .config import Config
from .remote import AutopcrRemoteClient, AutopcrRemoteError, RemoteMessage, RemoteResult
from .storage import REMOTE_FILE_CACHE_DIR

config = get_plugin_config(Config)
prefix = config.autopcr_prefix
address = config.autopcr_public_base_url
remote = AutopcrRemoteClient(config)
ACTIVE_GROUPS: set[str] = set()

sv_help = f"""
- {prefix}配置日常 一切的开始
- {prefix}清日常 [昵称] 无昵称则默认账号
- {prefix}清日常所有 清该qq号下所有号的日常
指令格式： 命令 昵称 参数，下述省略昵称，<>表示必填，[]表示可选，|表示分割
- {prefix}日常记录 查看清日常状态
- {prefix}日常报告 [0|1|2|3] 最近四次清日常报告
- {prefix}定时日志 查看定时运行状态
- {prefix}查角色 [昵称] 查看角色练度
- {prefix}查缺称号 查看缺少的称号
- {prefix}查缺角色 查看缺少的限定常驻角色
- {prefix}查ex装备 [会战] 查看ex装备库存
- {prefix}查探险编队 根据记忆碎片角色编队战力相当的队伍
- {prefix}查兑换角色碎片 [开换] 查询兑换特别角色的记忆碎片策略
- {prefix}查心碎 查询缺口心碎
- {prefix}查纯净碎片 查询缺口纯净碎片，国服六星+日服二专需求
- {prefix}查记忆碎片 [可刷取|大师币] 查询缺口记忆碎片，可按地图可刷取或大师币商店过滤
- {prefix}查装备 [<rank>] [fav] 查询缺口装备，rank为数字，只查询>=rank的角色缺口装备，fav表示只查询favorite的角色
- {prefix}查深域 查询深域通关情况
- {prefix}查公会深域 查询公会深域通关情况
- {prefix}刷图推荐 [<rank>] [fav] 查询缺口装备的刷图推荐，格式同上
- {prefix}公会支援 查询公会支援角色配置
- {prefix}卡池 查看当前卡池
- {prefix}编队 1 1 春妈 蝶妈 狗妈 水妈 礼妈 便捷设置编队
- {prefix}一键编队 1 1 队名1 星级角色1 星级角色2 ... 星级角色5 队名2 星级角色1 星级角色2 END 设置多队编队，队伍不足5人以END结尾
- {prefix}半月刊 查看半月刊
- {prefix}识图 [图片] 识别图片中的角色，返回一键编队文本
- {prefix}免费十连 <卡池id> 卡池id来自【{prefix}卡池】
- {prefix}来发十连 <卡池id> [抽到出] [单抽券|单抽] [编号小优先] [开抽] 赛博抽卡，谨慎使用。卡池id来自【{prefix}卡池】，[抽到出]表示抽到出货或达天井，默认十连，[单抽券]表示仅用厕纸，[单抽]表示宝石单抽，[标号小优先]指智能pickup时优先选择编号小的角色，[开抽]表示确认抽卡。已有up也可再次触发。
""".strip()


def escape(text: str) -> str:
    return html.escape(str(text), quote=False).replace("[", "&#91;").replace("]", "&#93;")


def _flatten_patterns(items: Iterable[Any]) -> list[str]:
    result: list[str] = []
    for item in items:
        if isinstance(item, (list, tuple, set)):
            result.extend(str(x) for x in item)
        else:
            result.append(str(item))
    return result


@dataclass(slots=True)
class Route:
    kind: str
    patterns: list[str]
    func: Callable[..., Coroutine[Any, Any, Any]]
    index: int


class ServiceRegistry:
    def __init__(self, name: str, **kwargs: Any):
        self.name = name
        self.help_ = kwargs.get("help_", "")
        self.routes: list[Route] = []
        self.logger = logger

    def on_fullmatch(self, *patterns: Any, **_: Any):
        pattern_list = _flatten_patterns(patterns)

        def decorator(func: Callable[..., Coroutine[Any, Any, Any]]):
            self.routes.append(Route("fullmatch", pattern_list, func, len(self.routes)))
            return func

        return decorator

    def on_prefix(self, *prefixes: Any, **_: Any):
        prefix_list = _flatten_patterns(prefixes)

        def decorator(func: Callable[..., Coroutine[Any, Any, Any]]):
            self.routes.append(Route("prefix", prefix_list, func, len(self.routes)))
            return func

        return decorator

    async def get_enable_groups(self) -> dict[int, set[str]]:
        return {int(group_id): set() for group_id in ACTIVE_GROUPS if group_id.isdigit()}


sv = ServiceRegistry(name="自动清日常", help_=sv_help)


@get_driver().on_startup
async def init() -> None:
    if not config.autopcr_startup_healthcheck:
        logger.info("autopcr adapter is running in remote HTTP mode")
        return
    try:
        await remote.health()
        logger.info("autopcr remote healthcheck succeeded")
    except AutopcrRemoteError as exc:
        logger.warning(f"autopcr remote healthcheck failed: {exc}")


class BotEvent:
    async def finish(self, msg: Any): ...
    async def send(self, msg: Any): ...
    async def target_qq(self) -> str: ...
    async def group_id(self) -> str: ...
    async def send_qq(self) -> str: ...
    async def message(self) -> list[str]: ...
    async def message_raw(self) -> str: ...
    async def image(self) -> list[str]: ...
    async def is_admin(self) -> bool: ...
    async def is_super_admin(self) -> bool: ...
    async def call_action(self, action: str, **kwargs: Any) -> dict[str, Any]: ...


class NoneBotEvent(BotEvent):
    def __init__(self, bot: BaseBot, event: MessageEvent, matcher: Matcher, *, message: Message | None = None, raw_message: str | None = None):
        self.bot = bot
        self.event = event
        self.matcher = matcher
        self.user_id = str(event.get_user_id())
        self._group_id = str(getattr(event, "group_id", ""))
        self.at_sb: list[str] = []
        self._message: list[str] = []
        self._raw_message = raw_message if raw_message is not None else event.get_plaintext()
        self._image: list[str] = []

        msg = message if message is not None else getattr(event, "message", Message())
        for segment in msg:
            seg_type = getattr(segment, "type", "")
            data = getattr(segment, "data", {}) or {}
            if seg_type == "at" and str(data.get("qq")) != "all":
                self.at_sb.append(str(data.get("qq")))
            elif seg_type == "text":
                text = str(data.get("text", ""))
                self._message += text.split()
            elif seg_type == "image":
                url = data.get("url") or data.get("file")
                if url:
                    self._image.append(str(url))

        if not self._message and self._raw_message:
            self._message = self._raw_message.split()

    async def target_qq(self) -> str:
        if len(self.at_sb) > 1:
            await self.finish("只能指定一个用户")
        return self.at_sb[0] if self.at_sb else self.user_id

    async def send_qq(self) -> str:
        return self.user_id

    async def message(self) -> list[str]:
        return self._message

    async def message_raw(self) -> str:
        return self._raw_message

    async def image(self) -> list[str]:
        return self._image

    async def send(self, msg: Any) -> None:
        await self.bot.send(self.event, msg)

    async def finish(self, msg: Any) -> None:
        await self.matcher.finish(msg)

    async def is_admin(self) -> bool:
        if await SUPERUSER(self.bot, self.event):
            return True
        sender = getattr(self.event, "sender", None)
        role = getattr(sender, "role", None) if sender is not None else None
        return role in {"admin", "owner"}

    async def is_super_admin(self) -> bool:
        return await SUPERUSER(self.bot, self.event)

    async def group_id(self) -> str:
        if not self._group_id:
            await self.finish("该指令只能在群聊中使用")
        return self._group_id

    async def call_action(self, action: str, **kwargs: Any) -> dict[str, Any]:
        return await self.bot.call_api(action, **kwargs)


def _message_after_prefix(message: Message, matched_prefix: str) -> tuple[Message, str]:
    copied = Message(message)
    if copied and copied[0].type == "text":
        text = str(copied[0].data.get("text", ""))
        if text.strip().startswith(matched_prefix):
            leading = len(text) - len(text.lstrip())
            start = leading + len(matched_prefix)
            copied[0].data["text"] = text[start:].lstrip()
            raw = "".join(str(seg) for seg in copied).strip()
            return copied, raw
    plain = str(message).strip()
    raw = plain[len(matched_prefix):].lstrip() if plain.startswith(matched_prefix) else plain
    return Message(raw), raw


def _match_route(plain_text: str) -> tuple[Route, str | None] | None:
    stripped = plain_text.strip()
    for route in [r for r in sv.routes if r.kind == "fullmatch"]:
        if stripped in route.patterns:
            return route, None
    prefix_routes = [r for r in sv.routes if r.kind == "prefix"]
    prefix_routes.sort(key=lambda r: (-max(len(p) for p in r.patterns), r.index))
    for route in prefix_routes:
        for item in sorted(route.patterns, key=len, reverse=True):
            if stripped.startswith(item):
                return route, item
    return None


async def _autopcr_rule(event: BaseEvent) -> bool:
    return isinstance(event, MessageEvent) and _match_route(event.get_plaintext()) is not None


autopcr_matcher = on_message(priority=5, block=False, rule=Rule(_autopcr_rule))


@autopcr_matcher.handle()
async def _handle_autopcr(bot: Bot, event: MessageEvent, matcher: Matcher, plain_text: str = EventPlainText()) -> None:
    if isinstance(event, GroupMessageEvent):
        ACTIVE_GROUPS.add(str(event.group_id))
    matched = _match_route(plain_text)
    if matched is None:
        return
    route, matched_prefix = matched
    if matched_prefix is None:
        message = Message("")
        raw = ""
    else:
        message, raw = _message_after_prefix(event.message, matched_prefix)
    botev = NoneBotEvent(bot, event, matcher, message=message, raw_message=raw)
    await route.func(botev)


async def _visible_user_ids(botev: BotEvent) -> list[str]:
    visible: set[str] = set()
    group_ids = set(ACTIVE_GROUPS)
    try:
        group_id = await botev.group_id()
        if group_id:
            group_ids.add(group_id)
    except Exception:
        pass

    if not group_ids:
        try:
            groups = await botev.call_action("get_group_list")
            group_ids.update(str(group.get("group_id")) for group in groups if group.get("group_id"))
        except Exception:
            group_ids = set()

    for group_id in sorted(group_ids):
        if not str(group_id).isdigit():
            continue
        try:
            members = await botev.call_action("get_group_member_list", group_id=int(group_id))
        except Exception:
            continue
        visible.update(str(member.get("user_id")) for member in members if member.get("user_id"))
    return sorted(visible)


async def _context(botev: BotEvent, *, include_visible_user_ids: bool = False) -> dict[str, Any]:
    group_id = ""
    try:
        group_id = await botev.group_id()
    except Exception:
        group_id = ""
    context = {
        "sender_qq": await botev.send_qq(),
        "group_id": group_id,
        "is_admin": await botev.is_admin(),
        "is_super_admin": await botev.is_super_admin(),
    }
    if include_visible_user_ids:
        context["visible_user_ids"] = await _visible_user_ids(botev)
    return context


async def _target_qq_for_operation(botev: BotEvent) -> str:
    target_qq = await botev.target_qq()
    sender_qq = await botev.send_qq()
    if sender_qq != target_qq and not await botev.is_admin():
        await botev.finish("只有管理员可以操作他人账号")
    return target_qq


async def _resolve_alias(botev: BotEvent, *, consume_single_free_arg: bool = False) -> str | None:
    msg = await botev.message()
    if not msg:
        return None
    if msg[0] in {"所有", "批量"}:
        return msg.pop(0)
    if consume_single_free_arg and len(msg) == 1:
        return msg.pop(0)

    qq = await botev.target_qq()
    try:
        info = await remote.user_info(qq)
    except AutopcrRemoteError:
        return None

    accounts = info.get("accounts") or []
    names = {str(item.get("alias") if isinstance(item, dict) else item) for item in accounts}
    if msg and msg[0] in names:
        return msg.pop(0)
    return None


async def _send_remote_result(botev: BotEvent, result: RemoteResult) -> None:
    if not result.messages:
        await botev.send("远端 autopcr 已完成请求，但没有返回内容")
        return
    for message in result.messages:
        await _send_remote_message(botev, message)


async def _send_remote_message(botev: BotEvent, message: RemoteMessage) -> None:
    if message.kind == "image":
        if message.url:
            await botev.send(MessageSegment.image(message.url))
        elif message.content:
            await botev.send(MessageSegment.image(message.content))
        return
    if message.kind == "autopcr_result_ref":
        await _send_autopcr_result_ref(botev, message)
        return
    if message.kind == "autopcr_daily_all_refs":
        await _send_autopcr_daily_all_refs(botev, message)
        return
    if message.kind in {"lines", "table", "autopcr_task_result", "autopcr_module_result"}:
        try:
            await botev.send(MessageSegment.image(_render_remote_message(message)))
        except Exception:
            logger.exception("failed to render autopcr remote structured message")
            await botev.send(_remote_message_text_fallback(message))
        return
    if message.kind == "file":
        await _send_remote_file(botev, message)
        return
    if message.text:
        await botev.send(message.text)


async def _send_autopcr_result_ref(botev: BotEvent, message: RemoteMessage) -> None:
    ref = message.result_ref or {}
    try:
        raw_result = await remote.fetch_result_ref(ref)
        result_type = str(ref.get("result_type") or "")
        if result_type == "single_result":
            rendered = _render_autopcr_module_result(raw_result)
        else:
            rendered = _render_autopcr_task_result(raw_result)
        await botev.send(MessageSegment.image(rendered))
    except Exception:
        logger.exception("failed to fetch/render autopcr result ref")
        await botev.send(_result_ref_text_fallback(ref))


async def _send_autopcr_daily_all_refs(botev: BotEvent, message: RemoteMessage) -> None:
    rows: list[list[str]] = []
    for ref in message.result_refs or []:
        alias = str(ref.get("alias") or ref.get("account") or "")
        status = "#" + _status_value(ref.get("status"))
        if ref.get("error"):
            rows.append([alias, str(ref.get("error")), status])
            continue
        try:
            raw_result = await remote.fetch_result_ref(ref)
            rows.append([alias, _task_result_last_log(raw_result), status])
        except Exception as exc:
            logger.exception("failed to fetch autopcr daily summary ref")
            rows.append([alias, str(exc), "#错误"])
    if not rows:
        await botev.send("远端 autopcr 已完成请求，但没有返回结果引用")
        return
    await botev.send(MessageSegment.image(_render_remote_table(["昵称", "清日常结果", "状态"], rows)))


async def _send_remote_file(botev: BotEvent, message: RemoteMessage) -> None:
    content = message.content
    filename = message.filename or "autopcr-result"
    if content is None and message.url:
        async with httpx.AsyncClient(timeout=config.autopcr_request_timeout, follow_redirects=True) as client:
            resp = await client.get(message.url)
            resp.raise_for_status()
            content = resp.content
            filename = filename or message.url.rsplit("/", 1)[-1]
    if content is None:
        if message.url:
            await botev.send(message.url)
        return

    path = REMOTE_FILE_CACHE_DIR / filename
    path.write_bytes(content)
    try:
        await botev.call_action(
            "upload_group_file",
            group_id=await botev.group_id(),
            file=str(path.resolve()),
            name=filename,
        )
    except Exception:
        logger.exception("failed to upload autopcr remote file")
        await botev.send(f"文件已生成但上传失败: {path}")


_BRIDGE_FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simhei.ttf",
]


@lru_cache(maxsize=8)
def _bridge_font(size: int) -> ImageFont.ImageFont:
    for path in _BRIDGE_FONT_CANDIDATES:
        if Path(path).exists():
            return ImageFont.truetype(path, size=size)
    return ImageFont.load_default(size=size)


def _measure_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> tuple[int, int]:
    bbox = draw.textbbox((0, 0), text or " ", font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> list[str]:
    wrapped: list[str] = []
    for paragraph in str(text).splitlines() or [""]:
        current = ""
        for char in paragraph:
            next_text = current + char
            if current and _measure_text(draw, next_text, font)[0] > max_width:
                wrapped.append(current)
                current = char
            else:
                current = next_text
        wrapped.append(current)
    return wrapped or [""]


def _render_remote_message(message: RemoteMessage) -> bytes:
    if message.kind == "table":
        return _render_remote_table(message.header or [], message.rows or [])
    if message.kind == "autopcr_task_result":
        return _render_autopcr_task_result(message.result or {})
    if message.kind == "autopcr_module_result":
        return _render_autopcr_module_result(message.result or {})
    return _render_remote_lines(message.lines or [])


def _render_autopcr_task_result(result: dict[str, Any]) -> bytes:
    rows: list[list[str]] = []
    modules = result.get("result") or {}
    for key in result.get("order") or []:
        if not isinstance(modules, dict):
            continue
        item = modules.get(str(key)) or modules.get(key)
        if not isinstance(item, dict):
            continue
        if str(item.get("log") or "") == "功能未启用":
            continue
        rows.append([
            str(len(rows) + 1),
            _clean_result_text(item.get("name")),
            _clean_result_text(item.get("config")),
            "#" + _status_value(item.get("status")),
            _clean_result_text(item.get("log")),
        ])
    return _render_remote_table(["序号", "名字", "配置", "状态", "结果"], rows)


def _task_result_last_log(result: dict[str, Any]) -> str:
    modules = result.get("result") if isinstance(result.get("result"), dict) else {}
    order = result.get("order") if isinstance(result.get("order"), list) else []
    if not order or not isinstance(modules, dict):
        return ""
    key = order[-1]
    item = modules.get(str(key)) or modules.get(key)
    if isinstance(item, dict):
        return _clean_result_text(item.get("log"))
    return ""


def _render_autopcr_module_result(result: dict[str, Any]) -> bytes:
    table = result.get("table") if isinstance(result.get("table"), dict) else {}
    table_data = table.get("data") if isinstance(table, dict) else []
    if isinstance(table_data, list) and len(table_data) > 1:
        return _render_autopcr_result_table(table)

    rows = [
        ["配置", _clean_result_text(result.get("config"))],
        ["状态", "#" + _status_value(result.get("status"))],
        ["结果", _clean_result_text(result.get("log"))],
    ]
    return _render_remote_table(["名字", _clean_result_text(result.get("name"))], rows)


def _render_autopcr_result_table(table: dict[str, Any]) -> bytes:
    header_items = table.get("header") if isinstance(table.get("header"), list) else []
    records = table.get("data") if isinstance(table.get("data"), list) else []
    columns = _flatten_autopcr_header(header_items)
    if not columns and records and isinstance(records[0], dict):
        columns = [(str(key), [str(key)]) for key in records[0].keys()]
    header = [label for label, _ in columns]
    rows = [
        [_stringify_result_value(_value_from_path(record, path)) for _, path in columns]
        for record in records
        if isinstance(record, dict)
    ]
    return _render_remote_table(header, rows)


def _flatten_autopcr_header(header_items: list[Any]) -> list[tuple[str, list[str]]]:
    columns: list[tuple[str, list[str]]] = []
    for item in header_items:
        if isinstance(item, dict):
            for key, children in item.items():
                group = str(key)
                child_items = children if isinstance(children, list) else [children]
                child_columns = _flatten_autopcr_header(child_items)
                if not child_columns:
                    columns.append((group, [group]))
                    continue
                for label, path in child_columns:
                    columns.append((f"{group}\n{label}", [group] + path))
        else:
            value = str(item)
            columns.append((value, [value]))
    return columns


def _value_from_path(record: dict[str, Any], path: list[str]) -> Any:
    value: Any = record
    for key in path:
        if isinstance(value, dict):
            value = value.get(key, "")
        else:
            return ""
    return value


def _clean_result_text(value: Any) -> str:
    return str(value or "").strip()


def _status_value(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("value") or value.get("name") or ""
    return str(value or "").lstrip("#")


def _stringify_result_value(value: Any) -> str:
    if isinstance(value, dict):
        return "\n".join(f"{key}: {_stringify_result_value(item)}" for key, item in value.items())
    if isinstance(value, list):
        return "\n".join(_stringify_result_value(item) for item in value)
    return str(value or "")


def _render_remote_lines(lines: list[str]) -> bytes:
    font = _bridge_font(24)
    pad_x, pad_y = 28, 24
    max_text_width = 1180
    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    wrapped = [
        subline
        for line in (lines or [""])
        for subline in _wrap_text(probe, str(line), font, max_text_width)
    ]
    line_height = max(_measure_text(probe, "国Ag", font)[1] + 12, 32)
    text_width = max((_measure_text(probe, line, font)[0] for line in wrapped), default=1)
    width = min(max_text_width + pad_x * 2, max(360, text_width + pad_x * 2))
    height = max(96, len(wrapped) * line_height + pad_y * 2)

    image = Image.new("RGB", (width, height), (255, 252, 245))
    draw = ImageDraw.Draw(image)
    draw.rectangle((12, 12, width - 13, height - 13), outline=(220, 211, 196), width=2)
    y = pad_y
    for line in wrapped:
        draw.text((pad_x, y), line, fill=(96, 78, 66), font=font)
        y += line_height
    return _image_to_png_bytes(image)


def _render_remote_table(header: list[str], rows: list[list[str]]) -> bytes:
    font = _bridge_font(22)
    header_font = _bridge_font(23)
    pad_x, pad_y = 14, 10
    max_cell_width = 360
    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    column_count = max(len(header), *(len(row) for row in rows), 1)
    normalized_header = [str(item) for item in header] + [""] * max(0, column_count - len(header))
    normalized_rows = [
        [str(cell) for cell in row] + [""] * max(0, column_count - len(row))
        for row in rows
    ]
    table_cells = [normalized_header] + normalized_rows
    wrapped_cells = [
        [
            _wrap_text(probe, cell, header_font if row_index == 0 else font, max_cell_width)
            for cell in row
        ]
        for row_index, row in enumerate(table_cells)
    ]

    col_widths: list[int] = []
    for col_index in range(column_count):
        width = 72
        for row_index, row in enumerate(wrapped_cells):
            cell_font = header_font if row_index == 0 else font
            width = max(width, *(_measure_text(probe, line, cell_font)[0] for line in row[col_index]))
        col_widths.append(min(max_cell_width + pad_x * 2, width + pad_x * 2))

    line_height = max(_measure_text(probe, "国Ag", font)[1] + 10, 30)
    header_line_height = max(_measure_text(probe, "国Ag", header_font)[1] + 10, 32)
    row_heights = [
        max((header_line_height if row_index == 0 else line_height) * len(cell) + pad_y * 2 for cell in row)
        for row_index, row in enumerate(wrapped_cells)
    ]
    width = sum(col_widths) + 2
    height = sum(row_heights) + 2

    image = Image.new("RGB", (width, height), (255, 252, 245))
    draw = ImageDraw.Draw(image)
    y = 1
    for row_index, row in enumerate(wrapped_cells):
        x = 1
        fill = (242, 232, 216) if row_index == 0 else (255, 252, 245)
        for col_index, cell_lines in enumerate(row):
            cell_width = col_widths[col_index]
            cell_height = row_heights[row_index]
            cell_fill = _cell_fill_color(table_cells[row_index][col_index], fill)
            draw.rectangle((x, y, x + cell_width, y + cell_height), fill=cell_fill, outline=(220, 211, 196), width=1)
            cell_font = header_font if row_index == 0 else font
            text_y = y + pad_y
            for line in cell_lines:
                draw.text((x + pad_x, text_y), line.lstrip("#"), fill=(96, 78, 66), font=cell_font)
                text_y += header_line_height if row_index == 0 else line_height
            x += cell_width
        y += row_heights[row_index]
    return _image_to_png_bytes(image)


def _cell_fill_color(text: str, default: tuple[int, int, int]) -> tuple[int, int, int]:
    if not str(text).startswith("#"):
        return default
    return {
        "成功": (225, 255, 181),
        "跳过": (200, 214, 250),
        "警告": (255, 215, 0),
        "中止": (255, 255, 0),
        "错误": (255, 100, 100),
        "致命": (139, 0, 0),
    }.get(str(text).lstrip("#"), default)


def _image_to_png_bytes(image: Image.Image) -> bytes:
    bio = BytesIO()
    try:
        image.save(bio, format="PNG", optimize=True)
        return bio.getvalue()
    finally:
        bio.close()
        image.close()


def _remote_message_text_fallback(message: RemoteMessage) -> str:
    if message.kind == "table":
        lines = ["\t".join(message.header or [])]
        lines.extend("\t".join(row) for row in message.rows or [])
        return "\n".join(line for line in lines if line)
    if message.kind == "autopcr_task_result":
        result = message.result or {}
        modules = result.get("result") or {}
        lines = []
        for key in result.get("order") or []:
            item = modules.get(str(key)) or modules.get(key) if isinstance(modules, dict) else None
            if isinstance(item, dict):
                lines.append(f"{item.get('name', key)}: {_status_value(item.get('status'))} {item.get('log', '')}")
        return "\n".join(lines)
    if message.kind == "autopcr_module_result":
        result = message.result or {}
        return f"{result.get('name', '')}: {_status_value(result.get('status'))}\n{result.get('log', '')}"
    if message.kind == "autopcr_result_ref":
        return _result_ref_text_fallback(message.result_ref or {})
    if message.kind == "autopcr_daily_all_refs":
        return "\n".join(
            f"{ref.get('alias') or ref.get('account')}: {_status_value(ref.get('status'))}"
            for ref in message.result_refs or []
        )
    return "\n".join(message.lines or [])


def _result_ref_text_fallback(ref: dict[str, Any]) -> str:
    label = ref.get("alias") or ref.get("account") or "autopcr"
    status = _status_value(ref.get("status"))
    raw_path = ref.get("raw_path") or ""
    return f"{label}: {status}\n结果引用暂时无法渲染: {raw_path}"


async def _call_remote(botev: BotEvent, call: Callable[[], Coroutine[Any, Any, RemoteResult]]) -> None:
    try:
        await _send_remote_result(botev, await call())
    except AutopcrRemoteError as exc:
        await botev.send(str(exc))


def check_final_args_be_empty(func: Callable[..., Coroutine[Any, Any, Any]]):
    async def wrapper(botev: BotEvent, *args: Any, **kwargs: Any):
        msg = await botev.message()
        if msg:
            await botev.finish("未知的参数：【" + " ".join(msg) + "】")
        await func(botev, *args, **kwargs)

    wrapper.__name__ = func.__name__
    return wrapper


@dataclass(slots=True)
class ToolInfo:
    name: str
    key: str
    config_parser: Callable[..., Coroutine[Any, Any, dict[str, Any]]]


tool_info: dict[str, ToolInfo] = {}


def register_tool(name: str, key: str):
    def wrapper(func: Callable[..., Coroutine[Any, Any, dict[str, Any]]]):
        tool_info[name] = ToolInfo(name=name, key=key, config_parser=func)
        return func

    return wrapper


def wrap_export(func: Callable[..., Coroutine[Any, Any, Any]]):
    async def wrapper(botev: BotEvent, *args: Any, **kwargs: Any):
        msg = await botev.message()
        command = msg[0] if msg else ""
        export = False
        if command.startswith("导出"):
            msg[0] = command.removeprefix("导出")
            export = True
            if not msg[0]:
                del msg[0]
        await func(botev=botev, export=export, *args, **kwargs)

    wrapper.__name__ = func.__name__
    return wrapper


def wrap_group(func: Callable[..., Coroutine[Any, Any, Any]]):
    async def wrapper(botev: BotEvent, *args: Any, **kwargs: Any):
        msg = await botev.message()
        command = msg[0] if msg else ""
        if command.startswith("群"):
            if not await botev.is_admin():
                await botev.finish("仅管理员可以操作群帐号")

            async def new_qq() -> str:
                return "g" + str(await botev.group_id())

            botev.target_qq = new_qq  # type: ignore[method-assign]
            msg[0] = command.removeprefix("群")
            if not msg[0]:
                del msg[0]
        await func(botev=botev, *args, **kwargs)

    wrapper.__name__ = func.__name__
    return wrapper


def wrap_tool(func: Callable[..., Coroutine[Any, Any, Any]]):
    async def wrapper(botev: BotEvent, *args: Any, **kwargs: Any):
        msg = await botev.message()
        tool = msg[0] if msg else ""
        for tool_name in tool_info:
            if tool.startswith(tool_name):
                msg[0] = tool.removeprefix(tool_name)
                if not msg[0]:
                    del msg[0]
                await func(botev=botev, tool=tool_info[tool_name], *args, **kwargs)
                return
        await botev.finish(f"未找到工具【{tool}】")

    wrapper.__name__ = func.__name__
    return wrapper


def wrap_config(func: Callable[..., Coroutine[Any, Any, Any]]):
    async def wrapper(botev: BotEvent, tool: ToolInfo, *args: Any, **kwargs: Any):
        parsed_config = await tool.config_parser(botev)
        await func(botev=botev, tool=tool, config=parsed_config, *args, **kwargs)

    wrapper.__name__ = func.__name__
    return wrapper


def require_super_admin(func: Callable[..., Coroutine[Any, Any, dict[str, Any]]]):
    async def wrapper(botev: BotEvent, *args: Any, **kwargs: Any) -> dict[str, Any]:
        if await botev.target_qq() != await botev.send_qq() and not await botev.is_super_admin():
            await botev.finish("仅超级管理员调用他人")
        return await func(botev=botev, *args, **kwargs)

    wrapper.__name__ = func.__name__
    return wrapper


@sv.on_fullmatch(["帮助自动清日常", f"{prefix}帮助"])
async def bangzhu_text(botev: BotEvent) -> None:
    await botev.finish(sv_help)


@sv.on_fullmatch(f"{prefix}配置日常")
async def config_clear_daily(botev: BotEvent) -> None:
    await botev.finish(remote.login_url())


@sv.on_fullmatch(f"{prefix}清日常所有")
async def clean_daily_all(botev: BotEvent) -> None:
    qq = await _target_qq_for_operation(botev)
    context = await _context(botev)
    await botev.send("开始清理该用户下所有日常")
    await _call_remote(botev, lambda: remote.run_daily_all(qq=qq, context=context))


@sv.on_prefix(f"{prefix}清日常")
async def clean_daily_from(botev: BotEvent) -> None:
    qq = await _target_qq_for_operation(botev)
    alias = await _resolve_alias(botev, consume_single_free_arg=True)
    await botev.send(f"开始为{escape(alias or '默认账号')}清理日常")
    context = await _context(botev)
    await _call_remote(botev, lambda: remote.run_daily(qq=qq, alias=alias, context=context))


@sv.on_prefix(f"{prefix}日常记录")
@check_final_args_be_empty
async def clean_daily_time(botev: BotEvent) -> None:
    qq = await _target_qq_for_operation(botev)
    await _call_remote(botev, lambda: remote.daily_records(qq=qq))


@sv.on_prefix(f"{prefix}日常报告")
async def clean_daily_result(botev: BotEvent) -> None:
    qq = await _target_qq_for_operation(botev)
    msg = await botev.message()
    result_id = 0
    if msg and msg[0].isdigit():
        result_id = int(msg.pop(0))
    alias = await _resolve_alias(botev, consume_single_free_arg=True)
    if msg:
        await botev.finish("未知的参数：【" + " ".join(msg) + "】")
    await _call_remote(botev, lambda: remote.daily_report(qq=qq, alias=alias, result_id=result_id))


@sv.on_fullmatch(f"{prefix}运行状态")
async def service_status(botev: BotEvent) -> None:
    await _call_remote(botev, remote.runtime_status)


@sv.on_fullmatch(f"{prefix}卡池")
async def gacha_current(botev: BotEvent) -> None:
    await _call_remote(botev, remote.gacha_current)


@sv.on_prefix(f"{prefix}定时日志")
async def cron_log(botev: BotEvent) -> None:
    qq = await _target_qq_for_operation(botev)
    msg = await botev.message()
    raw = await botev.message_raw()
    context = await _context(botev)
    await _call_remote(botev, lambda: remote.run_command(command="cron_log", qq=qq, raw_text=raw, args=msg, context=context))


@sv.on_prefix(f"{prefix}定时状态")
async def cron_status(botev: BotEvent) -> None:
    qq = await _target_qq_for_operation(botev)
    msg = await botev.message()
    raw = await botev.message_raw()
    context = await _context(botev)
    await _call_remote(botev, lambda: remote.run_command(command="cron_status", qq=qq, raw_text=raw, args=msg, context=context))


@sv.on_prefix(f"{prefix}定时统计")
async def cron_statistic(botev: BotEvent) -> None:
    qq = await _target_qq_for_operation(botev)
    msg = await botev.message()
    raw = await botev.message_raw()
    context = await _context(botev)
    await _call_remote(botev, lambda: remote.run_command(command="cron_statistic", qq=qq, raw_text=raw, args=msg, context=context))


@sv.on_fullmatch(f"{prefix}查禁用")
async def query_clan_battle_forbidden(botev: BotEvent) -> None:
    if not await botev.is_admin():
        await botev.finish("仅管理员可以调用")
    qq = await _target_qq_for_operation(botev)
    context = await _context(botev)
    await _call_remote(botev, lambda: remote.run_command(command="clan_forbid", qq=qq, raw_text="", args=[], context=context))


@sv.on_fullmatch(f"{prefix}查群禁用")
async def query_group_clan_battle_forbidden(botev: BotEvent) -> None:
    if not await botev.is_admin():
        await botev.finish("仅管理员可以调用")
    qq = "g" + str(await botev.group_id())
    context = await _context(botev)
    await _call_remote(botev, lambda: remote.run_command(command="group_clan_forbid", qq=qq, raw_text="", args=[], context=context))


@sv.on_fullmatch(f"{prefix}查内鬼")
async def find_ghost(botev: BotEvent) -> None:
    qq = await _target_qq_for_operation(botev)
    context = await _context(botev, include_visible_user_ids=True)
    await _call_remote(botev, lambda: remote.run_command(command="find_ghost", qq=qq, raw_text="", args=[], context=context))


@sv.on_fullmatch(f"{prefix}清内鬼")
async def clean_ghost(botev: BotEvent) -> None:
    if not await botev.is_admin():
        await botev.finish("仅管理员可以调用")
    qq = await _target_qq_for_operation(botev)
    context = await _context(botev, include_visible_user_ids=True)
    await _call_remote(botev, lambda: remote.run_command(command="clean_ghost", qq=qq, raw_text="", args=[], context=context))


@sv.on_prefix(f"{prefix}")
@wrap_export
@wrap_group
@wrap_tool
@wrap_config
async def tool_used(botev: BotEvent, tool: ToolInfo, config: dict[str, Any], export: bool) -> None:
    qq = await _target_qq_for_operation(botev)
    alias = await _resolve_alias(botev)
    args = list(await botev.message())
    raw = await botev.message_raw()
    context = await _context(botev)
    await botev.send(f"开始为{escape(alias or '默认账号')}执行【{tool.name}】")
    await _call_remote(
        botev,
        lambda: remote.run_tool(
            qq=qq,
            alias=alias,
            tool_name=tool.name,
            tool_key=tool.key,
            config=config,
            export=export,
            raw_text=raw,
            args=args,
            context=context,
        ),
    )


@sv.on_prefix(f"{prefix}识图")
async def ocr_team(botev: BotEvent) -> None:
    qq = await _target_qq_for_operation(botev)
    args = await botev.message()
    raw = await botev.message_raw()
    images = await botev.image()
    if not images:
        await botev.finish("未识别到图片!")
    context = await _context(botev)
    context["images"] = images
    await _call_remote(botev, lambda: remote.run_command(command="ocr_team", qq=qq, raw_text=raw, args=args, context=context))


def is_args_exist(msg: list[str], key: str) -> bool:
    if key in msg:
        msg.remove(key)
        return True
    return False


def recover_text_by_tokens(raw_text: str, tokens: list[str]) -> str:
    if not tokens:
        return ""
    pattern = r"\s+".join(re.escape(token) for token in tokens)
    match = re.search(pattern, raw_text, flags=re.S)
    if match:
        return raw_text[match.start():match.end()]
    return " ".join(tokens)


@register_tool("公会支援", "get_clan_support_unit")
async def clan_support(botev: BotEvent) -> dict[str, Any]:
    return {}


@register_tool("查心碎", "get_need_xinsui")
async def find_xinsui(botev: BotEvent) -> dict[str, Any]:
    return {}


@register_tool("查记忆碎片", "get_need_memory")
async def find_memory(botev: BotEvent) -> dict[str, Any]:
    memory_demand_consider_unit = "所有"
    msg = await botev.message()
    if is_args_exist(msg, "可刷取"):
        memory_demand_consider_unit = "地图可刷取"
    elif is_args_exist(msg, "大师币"):
        memory_demand_consider_unit = "大师币商店"
    return {"memory_demand_consider_unit": memory_demand_consider_unit}


@register_tool("查纯净碎片", "get_need_pure_memory")
async def find_pure_memory(botev: BotEvent) -> dict[str, Any]:
    return {}


@register_tool("来发十连", "gacha_start")
@require_super_admin
async def shilian(botev: BotEvent) -> dict[str, Any]:
    msg = await botev.message()
    pool_id = msg.pop(0) if msg else ""
    cc_until_get = is_args_exist(msg, "抽到出")
    really_do = is_args_exist(msg, "开抽")
    single_ticket = is_args_exist(msg, "单抽券")
    single = is_args_exist(msg, "单抽")
    small_first = is_args_exist(msg, "编号小优先")

    if single_ticket and single:
        await botev.finish("单抽券和单抽只能选一个")
    if not really_do:
        gacha_method = "单抽券" if single_ticket else "单抽" if single else "十连"
        lines = [f"卡池{pool_id}"]
        if cc_until_get:
            lines.append("抽到出")
        if small_first:
            lines.append("编号小优先")
        lines += [gacha_method, "确认无误，消息末尾加上【开抽】即可开始抽卡"]
        await botev.finish("\n".join(lines))
    return {
        "pool_id": pool_id,
        "cc_until_get": cc_until_get,
        "gacha_method": "单抽券" if single_ticket else "单抽" if single else "十连",
        "gacha_start_auto_select_pickup_min_first": small_first,
    }


@register_tool("查装备", "get_need_equip")
async def find_equip(botev: BotEvent) -> dict[str, Any]:
    like_unit_only = False
    start_rank = None
    msg = await botev.message()
    like_unit_only = is_args_exist(msg, "fav")
    if msg and msg[0].isdigit():
        start_rank = int(msg.pop(0))
    return {"start_rank": start_rank, "like_unit_only": like_unit_only}


@register_tool("刷图推荐", "get_normal_quest_recommand")
async def quest_recommand(botev: BotEvent) -> dict[str, Any]:
    return await find_equip(botev)


@register_tool("查缺角色", "missing_unit")
async def find_missing_unit(botev: BotEvent) -> dict[str, Any]:
    return {}


@register_tool("查缺称号", "missing_emblem")
async def find_missing_emblem(botev: BotEvent) -> dict[str, Any]:
    return {}


@register_tool("查角色", "search_unit")
async def search_box(botev: BotEvent) -> dict[str, Any]:
    msg = await botev.message()
    if not msg:
        await botev.finish("请指定角色昵称")
    return {"search_unit_name": msg.pop(0)}


@register_tool("刷新box", "refresh_box")
async def refresh_box(botev: BotEvent) -> dict[str, Any]:
    return {}


@register_tool("查探险编队", "travel_team_view")
async def find_travel_team_view(botev: BotEvent) -> dict[str, Any]:
    return {}


@register_tool("查ex装备", "ex_equip_info")
async def ex_equip_info(botev: BotEvent) -> dict[str, Any]:
    msg = await botev.message()
    return {"ex_equip_info_cb_only": is_args_exist(msg, "会战")}


@register_tool("查兑换角色碎片", "redeem_unit_swap")
async def redeem_unit_swap(botev: BotEvent) -> dict[str, Any]:
    msg = await botev.message()
    return {"redeem_unit_swap_do": is_args_exist(msg, "开换")}


@register_tool("半月刊", "half_schedule")
async def half_schedule(botev: BotEvent) -> dict[str, Any]:
    return {}


@register_tool("查深域", "find_talent_quest")
async def find_talent_quest(botev: BotEvent) -> dict[str, Any]:
    return {}


@register_tool("查公会深域", "find_clan_talent_quest")
async def find_clan_talent_quest(botev: BotEvent) -> dict[str, Any]:
    return {}


@register_tool("查box", "get_box_table")
async def get_box_table(botev: BotEvent) -> dict[str, Any]:
    msg = await botev.message()
    box_all_unit = is_args_exist(msg, "所有")
    if not msg and not box_all_unit:
        await botev.finish("请指定角色或添加【所有】参数")
    unit_names = list(msg)
    msg.clear()
    return {"box_unit_names": unit_names, "box_all_unit": box_all_unit}


@register_tool("免费十连", "free_gacha")
async def free_gacha(botev: BotEvent) -> dict[str, Any]:
    msg = await botev.message()
    gacha_id = int(msg.pop(0)) if msg and msg[0].isdigit() else 0
    return {"free_gacha_select_ids": [gacha_id], "today_end_gacha_no_do": False}


@register_tool("一键编队", "set_my_party2")
async def set_my_party_multi(botev: BotEvent) -> dict[str, Any]:
    raw_msg = await botev.message_raw()
    msg = await botev.message()
    tab_start_num = int(msg.pop(0)) if msg and msg[0].isdigit() else 1
    party_start_num = int(msg.pop(0)) if msg and msg[0].isdigit() else 1
    teams_text = recover_text_by_tokens(raw_msg, msg)
    msg.clear()
    return {"tab_start_num2": tab_start_num, "party_start_num2": party_start_num, "set_my_party_text2": teams_text}
