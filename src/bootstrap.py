import nonebot
from nonebot.adapters.onebot.v11 import Adapter as OnebotAdapter


def init_nonebot_app():
    nonebot.init()

    driver = nonebot.get_driver()

    # SAA（跨平台消息发送）必须在使用前加载
    nonebot.load_plugin("nonebot_plugin_saa")

    # ── Adapter 注册 ───────────────────────────────────────────────────────
    driver.register_adapter(OnebotAdapter)

    # ── 加载外部插件 ─────────────────────────────────────────────────────
    nonebot.load_plugin("nonebot_plugin_analysis_bilibili")
    nonebot.load_plugin("nonebot_plugin_memes")
    nonebot.load_plugin("nonebot_plugin_whateat_pic")
    nonebot.load_plugin("nonebot_plugin_wordcloud")
    nonebot.load_plugin("nonebot_plugin_guess_song")
    nonebot.load_plugins("src/plugins")

    return driver
