import os

import nonebot
from nonebot.adapters.onebot.v11 import Adapter as OnebotAdapter


def main():
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

    # ── 本地调试模式 ─────────────────────────────────────────────────────
    if os.getenv("ENABLE_CONSOLE_DEBUG"):
        _register_console_debug()

    nonebot.run()


def _register_console_debug():
    """注册 stdin 调试交互（仅本地开发）。

    启用后可在终端直接输入命令（如 /mai.b50），
    Bot 回复会打印到 stdout。图片保存为临时文件。
    """
    import asyncio
    import sys
    import tempfile
    import pathlib

    from nonebot.internal.adapter import Bot as BaseBot
    from nonebot.internal.adapter import Event as BaseEvent
    from nonebot.message import handle_event
    from nonebot.log import logger

    class _ConsoleBot(BaseBot):
        async def send(self, event, message, **kwargs):
            """将 SAA 消息段打印到终端，图片保存到临时文件。"""
            segments = message if isinstance(message, list) else [message]
            for seg in segments:
                seg_type = getattr(seg, "type", None)
                seg_data = getattr(seg, "data", {})
                if seg_type == "text":
                    print(f"[Bot] {seg_data.get('text', '')}")
                elif seg_type == "image":
                    raw = seg_data.get("raw")
                    if raw:
                        tmp = pathlib.Path(tempfile.gettempdir()) / f"bot_img_{id(raw)}.png"
                        tmp.write_bytes(raw)
                        print(f"[Bot] [图片已保存: {tmp}]")
                    else:
                        print(f"[Bot] [图片: {seg_data}]")
                elif seg_type == "reply":
                    print(f"[Bot] [回复 msg_id={seg_data.get('id', '?')}]")
                else:
                    print(f"[Bot] [{seg_type}: {seg_data}]")

    class _ConsoleEvent(BaseEvent):
        def get_type(self) -> str:
            return "message"

        def get_event_name(self) -> str:
            return "console.message"

        def get_event_description(self) -> str:
            return f"[Console] {self.get_plaintext()[:50]}"

        def get_user_id(self) -> str:
            return "console_user"

        def get_session_id(self) -> str:
            return "console_session"

        def is_tome(self) -> bool:
            return True

        def get_message(self):
            from nonebot.adapters import Message
            raw = self.model_dump().get("_raw_text", "")
            return Message(raw)

        def get_plaintext(self) -> str:
            return self.model_dump().get("_raw_text", "")

    bot = _ConsoleBot(adapter=None, self_id="console_bot")
    logger.info("[ConsoleDebug] 本地调试模式已启用，在终端输入命令（如 /mai.b50，输入 quit 退出）")
    print("[ConsoleDebug] 本地调试模式已启用，输入命令开始调试（quit 退出）")
    console_task: asyncio.Task | None = None

    async def _read_loop():
        while True:
            try:
                line = await asyncio.to_thread(sys.stdin.readline)
            except Exception:
                break
            if not line:
                break
            text = line.strip()
            if not text:
                continue
            if text.lower() in ("quit", "exit"):
                print("[ConsoleDebug] 退出调试模式")
                break
            event = _ConsoleEvent({"_raw_text": text, "message_id": 0})
            try:
                await handle_event(bot, event)
            except Exception:
                logger.opt(exception=True).error("[ConsoleDebug] 命令处理失败")

    driver = nonebot.get_driver()

    @driver.on_startup
    async def _start_console_debug():
        nonlocal console_task
        console_task = asyncio.create_task(_read_loop())

    @driver.on_shutdown
    async def _stop_console_debug():
        if console_task and not console_task.done():
            console_task.cancel()
            try:
                await console_task
            except asyncio.CancelledError:
                pass


if __name__ == "__main__":
    main()
