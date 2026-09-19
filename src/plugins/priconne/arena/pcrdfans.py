import time
import random
import string
import json

from nonebot import require

require("nonebot_plugin_htmlrender")

from nonebot_plugin_htmlrender.browser import get_browser
from playwright.async_api import Page


class PCRDSigner:
    _instance = None
    _page: Page = None # type: ignore

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(PCRDSigner, cls).__new__(cls)
        return cls._instance

    @classmethod
    async def get_instance(cls):
        if cls._instance is None or cls._instance._page is None:
            cls._instance = PCRDSigner()
            await cls._instance._init_page()
        return cls._instance

    async def _init_page(self):
        """初始化持久化的签名环境。"""
        browser = await get_browser()
        self._page = await browser.new_page()

        try:
            await self._page.goto("https://pcrdfans.com/battle", wait_until="networkidle")
            await self._page.wait_for_function("() => typeof window.pcrutil === 'function'", timeout=30000)
        except Exception as e:
            print(f"[PCRD-Signer] 环境初始化失败: {e}")
            raise e

    def _transform_nonce_python(self, nonce_str: str) -> int:
        """纯 Python 复刻的 _0x56261b 逻辑，作为备用或预计算"""
        h = 0x1bf52
        for char in reversed(nonce_str):
            h = (0x309 * h ^ ord(char)) & 0xFFFFFFFF
        return h >> 3

    async def get_sign(self, id_list, region, page_num=1):
        """
        调用劫持到的闭包函数生成切噜语签名
        """
        if self._page.is_closed():
            await self._init_page()

        nonce = ''.join(random.choices(string.ascii_lowercase + string.digits, k=16))
        ts = int(time.time())
        id_list_query = [x * 100 + 1 for x in id_list]

        payload = {
            "def": id_list_query,
            "language": 0,
            "nonce": nonce,
            "page": page_num,
            "region": region,
            "sort": 1,
            "ts": ts,
        }

        # 将 payload 序列化为 JSON 字符串
        raw_payload = json.dumps(payload, separators=(',', ':'))
        
        # 预计算 transformed_nonce
        transformed = self._transform_nonce_python(nonce)

        _sign = await self._page.evaluate("""
            async ([raw, nonce, transformed]) => {
                try {
                    return window.pcrutil(raw, nonce, transformed) || null;
                } catch (e) {
                    return null;
                }
            }
        """, [raw_payload, nonce, transformed])

        if not _sign:
            return None

        payload["_sign"] = _sign
        return payload
