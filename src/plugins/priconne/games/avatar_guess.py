# ref: https://github.com/GWYOG/GWYOG-Hoshino-plugins/blob/master/pcravatarguess
# Originally written by @GWYOG
# Reflacted by @Ice9Coffee
# GPL-3.0 Licensed
# Thanks to @GWYOG for his great contribution!

import asyncio
import random

from nonebot.adapters.onebot.v11 import MessageSegment as Seg

from .. import _pcr_data, chara
from ..compat import Service
from ..compat.util import filt_message, pic2b64

from . import GameMaster

PATCH_SIZE = 32
ONE_TURN_TIME = 20
BLACKLIST_ID = [1072, 1908, 4031, 9000]

gm = GameMaster()
sv = Service(
    "pcr-avatar-guess",
    help_="""
[猜头像] 猜猜bot随机发送的头像的一小部分来自哪位角色
[猜头像排行] 显示小游戏的群排行榜(只显示前十)
""".strip(),
)


@sv.on_fullmatch("猜头像排行", "猜头像排名", "猜头像排行榜", "猜头像群排行")
async def description_guess_group_ranking(bot, ev):
    ranking = await gm.db.get_ranking(ev.group_id)
    msg = ["【猜头像小游戏排行榜】"]
    for i, item in enumerate(ranking):
        uid, count = item
        m = await bot.get_group_member_info(group_id=ev.group_id, user_id=uid)
        name = filt_message(m.get("card") or "") or filt_message(m.get("nickname") or "") or str(uid)
        msg.append(f"第{i + 1}名：{name} 猜对{count}次")
    await bot.send(ev, "\n".join(msg))


@sv.on_fullmatch("猜头像")
async def avatar_guess(bot, ev):
    if gm.is_playing(ev.group_id):
        await bot.finish(ev, "游戏仍在进行中…")
    with gm.start_game(ev.group_id) as game:
        ids = list(_pcr_data.CHARA_NAME.keys())
        game.answer = random.choice(ids), random.choice((3, 6))
        while chara.is_npc(game.answer[0]):
            game.answer = random.choice(ids), random.choice((3, 6))
        c = chara.fromid(game.answer[0], game.answer[1])
        res = await c.get_icon()
        img = res.open()
        w, h = img.size
        l = random.randint(0, max(0, w - PATCH_SIZE))
        u = random.randint(0, max(0, h - PATCH_SIZE))
        cropped = img.crop((l, u, l + PATCH_SIZE, u + PATCH_SIZE))
        seg = Seg.image(pic2b64(cropped))
        await bot.send(ev, f"猜猜这个图片是哪位角色头像的一部分?({ONE_TURN_TIME}s后公布答案) {seg}")
        await asyncio.sleep(ONE_TURN_TIME)
        if game.winner:
            return
    icon_seg = await c.get_icon_cqcode()
    await bot.send(ev, f"正确答案是：{c.name} {icon_seg}\n很遗憾，没有人答对~")


@sv.on_message()
async def on_input_chara_name(bot, ev):
    game = gm.get_game(ev.group_id)
    if not game or game.winner:
        return
    c = chara.fromname(ev.message.extract_plain_text(), game.answer[1])
    if c.id != chara.UNKNOWN and c.id == game.answer[0]:
        game.winner = ev.user_id
        n = await game.record()
        icon_seg = await c.get_icon_cqcode()
        msg = f"正确答案是：{c.name}{icon_seg}\n{Seg.at(ev.user_id)}猜对了，真厉害！TA已经猜对{n}次了~\n(此轮游戏将在几秒后自动结束，请耐心等待)"
        await bot.send(ev, msg)
