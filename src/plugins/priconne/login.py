import os
import traceback
from asyncio import Lock

from nonebot import logger

from .captcha import CaptchaContext, create_captcha_verifier
from .compat import Service
from .credentials import build_stored_account
from .pcrclient import pcrclient, bsdkclient
from .util.tools import DATA_PATH, check_client, write_config

sv_help = '【绑定账号+账号+密码】加号为空格'

sv = Service('你只需要好好出刀', help_=sv_help, visible=True)


@sv.on_fullmatch('绑定账号帮助', only_to_me=False)
async def send_jjchelp(bot, ev):
    await bot.send_private_msg(user_id=ev.user_id, message=sv_help)

account_path = os.path.join(DATA_PATH, 'account')
bind_lck = Lock()
qu_bind_lck = Lock()
client = None
client_cache = {}


async def query(acccount_info, is_force=False, captcha_context: CaptchaContext | None = None):
    try:
        acccount_info = acccount_info[0].copy()
        player = acccount_info.get('account', 0) or acccount_info.get('uid')
        if player in client_cache and not is_force:
            client = client_cache[player]
            if await check_client(client):
                return client
        client = pcrclient(bsdkclient(acccount_info, create_captcha_verifier(captcha_context)))
        await client.login()
        if await check_client(client):
            client_cache[player] = client
            return client
        raise Exception(f"登录失败，请重试")
    except Exception as e:
        raise Exception(f"未知错误：{e}")


@sv.on_prefix("绑定账号")
async def bind_support(bot, ev):
    acccount = {'platform': 2, 'channel': 1, }
    content = ev.message.extract_plain_text().split()
    qq_id = ev.user_id
    if len(content) != 2:
        await bot.send_private_msg(user_id=qq_id, message=sv_help)
    else:
        acccount["account"] = content[0]
        acccount['password'] = content[1]
        try:
            captcha_context = CaptchaContext(bot=bot, user_id=qq_id)
            client = await query([acccount.copy()], True, captcha_context)
            if await check_client(client):
                bound_account = build_stored_account(acccount, client.uid, client.access_key)
                await write_config(os.path.join(account_path, f'{qq_id}.json'), [bound_account])
                await bot.send_private_msg(user_id=qq_id, message="绑定成功")
        except Exception as e:
            logger.info(traceback.format_exc())
            await bot.send_private_msg(user_id=qq_id, message="绑定失败" + str(e))
