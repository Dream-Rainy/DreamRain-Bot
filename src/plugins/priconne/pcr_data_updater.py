import os
import random

from nonebot import get_bot, logger
from nonebot.adapters.onebot.v11 import Bot
from nonebot.drivers import Driver

from . import chara
from .compat import Service, aiorequests

sv = Service("pcr-data-updater", visible=False)


def _get_superusers() -> list:
    try:
        driver: Driver = get_bot().driver
        return list(getattr(driver.config, "superusers", set()))
    except Exception:
        return []


async def report_to_su(sess, msg_with_sess, msg_wo_sess):
    if sess:
        await sess.send(msg_with_sess)
    else:
        try:
            bot: Bot = get_bot()
            superusers = _get_superusers()
            if superusers:
                await bot.send_private_msg(user_id=int(superusers[0]), message=msg_wo_sess)
        except Exception as e:
            logger.error(f"pcr_data_updater report_to_su failed: {e}")


async def pull_chara(sess=None):
    try:
        rsp = await aiorequests.get(
            "https://raw.githubusercontent.com/Ice9Coffee/LandosolRoster/master/_pcr_data.py",
            timeout=300,
        )
        rsp.raise_for_status()
        text = await rsp.text

        filename = os.path.join(os.path.dirname(__file__), "_pcr_data.py")
        with open(filename, "w", encoding="utf8") as f:
            f.write(text)
        result = chara.roster.update()

    except Exception as e:
        logger.exception(e)
        await report_to_su(sess, f"Error: {e}", f"pcr_data定时更新时遇到错误：\n{e}")
        return

    result_msg = f"角色别称导入成功 {result['success']}，重名 {result['duplicate']}"
    await report_to_su(sess, result_msg, f"pcr_data定时更新：\n{result_msg}")


@sv.on_command("更新花名册", aliases=("重载花名册",))
async def cmd_pull_chara(session):
    superusers = _get_superusers()
    if superusers and session.ctx.get("user_id") not in (int(u) for u in superusers):
        return
    await pull_chara(session)


sv.scheduled_job("cron", hour=5, jitter=300)(pull_chara)
