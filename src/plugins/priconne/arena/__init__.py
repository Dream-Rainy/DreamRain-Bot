import asyncio
from typing import Optional

from nonebot import get_driver, logger
from nonebot.adapters.onebot.v11 import Message

from .. import chara
from .._pcr_data import CHARA_NAME  # noqa: F401 - used by other modules
from ..compat import Service, priv
from .qq_context_requests import (
    RegionEnum,
    PopRequest,
    gs_qqid2request,
    QueryRequestContext,
)

sv_help = '''
查询请发送"bjjc/rjjc/tjjc+防守队伍"，无需+号。可以分开发送。
防守队伍可以是五个角色的昵称，也可以是截图。
截图支持局部图片和全局图片，支持多队查询，支持未定队伍查询，支持近似查询。
截图与bjjc/rjjc/tjjc可以分开发送。
竞技场预热状态：查看头像字典预热状态。
竞技场预热头像：管理员手动触发头像预热与重建字典。
源码：https://github.com/watermellye/arena
'''.strip()

sv = Service('pcr-arena', help_=sv_help)
_icon_warmup_started = False

gs_prefix_all = ('怎么拆', '怎么解', '怎么打', '如何拆', '如何解', '如何打', 'jjc查询')
gs_prefix_bilibili = tuple(["bjjc"] + ['b' + x for x in gs_prefix_all] + ['B' + x for x in gs_prefix_all])
gs_prefix_taiwan = tuple(["tjjc"] + ['t' + x for x in gs_prefix_all] + ['T' + x for x in gs_prefix_all])
gs_prefix_japan = tuple(["rjjc"] + ['r' + x for x in gs_prefix_all] + ['R' + x for x in gs_prefix_all])


def IsEmptyMessage(message: Message) -> bool:
    return all(x.type == 'text' and x.data.get('text', '').strip() == '' for x in message)


def GetImageUrlFromMessage(message: Message) -> Optional[str]:
    images = [x.data for x in message if x.type == 'image']
    url = images[0].get("url", None) if images else None
    if url is not None:
        url = url.replace("&amp;", "&").split(",file_size=")[0]
    return url


async def QueryArenaInterface(bot, ev, msg: Message, region: RegionEnum):
    image_url = GetImageUrlFromMessage(msg)
    if image_url:
        await QueryArenaImageAsync(image_url, region, bot, ev)
    else:
        await QueryArenaTextAsync(msg.extract_plain_text().strip(), region, bot, ev)


@sv.on_prefix(gs_prefix_all)
async def QueryAllInterface(bot, ev):
    if IsEmptyMessage(ev.message):
        await bot.send(ev, sv.help_)
    else:
        await QueryArenaInterface(bot, ev, ev.message, RegionEnum.All)
        await bot.send(ev, '请使用 bjjc/rjjc/tjjc 以过滤查询的服务器。')


@sv.on_prefix(gs_prefix_bilibili)
async def QueryBilibiliInterface(bot, ev):
    from .qq_context_requests import gs_seconds_to_wait
    if IsEmptyMessage(ev.message):
        await bot.send(ev, f'已收到查作业（B服）请求，请在 {gs_seconds_to_wait} 秒内发送防守队伍截图')
        gs_qqid2request[ev.user_id] = QueryRequestContext(RegionEnum.Bilibili)
    else:
        await QueryArenaInterface(bot, ev, ev.message, RegionEnum.Bilibili)


@sv.on_prefix(gs_prefix_taiwan)
async def QueryTaiwanInterface(bot, ev):
    from .qq_context_requests import gs_seconds_to_wait
    if IsEmptyMessage(ev.message):
        await bot.send(ev, f'已收到查作业（台服）请求，请在 {gs_seconds_to_wait} 秒内发送防守队伍截图')
        gs_qqid2request[ev.user_id] = QueryRequestContext(RegionEnum.Taiwan)
    else:
        await QueryArenaInterface(bot, ev, ev.message, RegionEnum.Taiwan)


@sv.on_prefix(gs_prefix_japan)
async def QueryJapanInterface(bot, ev):
    from .qq_context_requests import gs_seconds_to_wait
    if IsEmptyMessage(ev.message):
        await bot.send(ev, f'已收到查作业（日服）请求，请在 {gs_seconds_to_wait} 秒内发送防守队伍截图')
        gs_qqid2request[ev.user_id] = QueryRequestContext(RegionEnum.Japan)
    else:
        await QueryArenaInterface(bot, ev, ev.message, RegionEnum.Japan)


@sv.on_message()
async def QueryArenaMessageContextInterface(bot, ev):
    image_url = GetImageUrlFromMessage(ev.message)
    if not image_url:
        return
    req = PopRequest(ev.user_id)
    if req is None:
        return
    await QueryArenaImageAsync(image_url, req.region, bot, ev)


async def QueryArenaImageAsync(image_url: str, region: RegionEnum, bot, ev) -> None:
    from .old_main import _QueryArenaImageAsync
    await _QueryArenaImageAsync(image_url, Region2Int(region), bot, ev)


async def QueryArenaTextAsync(text: str, region: RegionEnum, bot, ev) -> None:
    from .old_main import _QueryArenaTextAsync
    await _QueryArenaTextAsync(text, Region2Int(region), bot, ev)


def Region2Int(region: RegionEnum) -> int:
    if region == RegionEnum.All:
        return 1
    if region == RegionEnum.Bilibili:
        return 2
    if region == RegionEnum.Taiwan:
        return 3
    if region == RegionEnum.Japan:
        return 4
    return -1


async def _run_icon_warmup(force: bool) -> dict:
    return await chara.warmup_icons(
        force=force,
        stars=(1, 3, 6),
        concurrency=16,
        rebuild_arena_dic=True,
    )


@get_driver().on_startup
async def _arena_icon_warmup_startup() -> None:
    global _icon_warmup_started
    if _icon_warmup_started:
        return
    _icon_warmup_started = True

    async def _task():
        try:
            result = await _run_icon_warmup(force=False)
            if result.get("skipped"):
                logger.info("Arena icon warmup skipped: already completed")
            else:
                state = result.get("state", {})
                logger.info(
                    f"Arena icon warmup done: success={state.get('success_count', 0)} "
                    f"fail={state.get('fail_count', 0)}"
                )
        except Exception as e:
            logger.error(f"Arena icon warmup failed: {e}")

    asyncio.create_task(_task())


@sv.on_fullmatch("竞技场预热状态")
async def arena_warmup_status(bot, ev):
    state = chara.get_icon_warmup_state()
    if not state:
        await bot.send(ev, "未找到预热状态，尚未执行过预热。")
        return
    await bot.send(
        ev,
        "竞技场头像预热状态：\n"
        f"completed: {state.get('completed')}\n"
        f"completed_at: {state.get('completed_at', '-')}\n"
        f"unit_count: {state.get('unit_count', 0)}\n"
        f"stars: {state.get('stars', [])}\n"
        f"attempted: {state.get('attempted', 0)}\n"
        f"success: {state.get('success_count', 0)}\n"
        f"failed: {state.get('fail_count', 0)}",
    )


@sv.on_fullmatch("竞技场预热头像")
async def arena_warmup_manual(bot, ev):
    if not priv.check_priv(ev, priv.ADMIN):
        await bot.send(ev, "权限不足")
        return
    await bot.send(ev, "开始预热竞技场头像并重建识别字典，请稍等...")
    result = await _run_icon_warmup(force=True)
    state = result.get("state", {})
    await bot.send(
        ev,
        "预热完成：\n"
        f"attempted: {state.get('attempted', 0)}\n"
        f"success: {state.get('success_count', 0)}\n"
        f"failed: {state.get('fail_count', 0)}",
    )
