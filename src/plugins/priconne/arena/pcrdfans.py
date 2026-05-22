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
        """初始化持久化的签名环境，并注入核心劫持逻辑"""
        browser = await get_browser()
        self._page = await browser.new_page()
        
        # 1. 在页面加载任何脚本前，注入“内鬼”脚本，劫持 _makeFuncWrapper
        # 即使它是局部变量，在它诞生的那一刻我们也要给它一个全局引用
        await self._page.add_init_script("""
            (function() {
                const originalDefineProperty = Object.defineProperty;
                Object.defineProperty = function(obj, prop, descriptor) {
                    if (prop === '_makeFuncWrapper' || prop === 'value') {
                        const originalFactory = descriptor.value;
                        descriptor.value = function(_0x47eb44) {
                            // 【核心修改】保存这个特定运行时的 this
                            window.REAL_THIS = this; 
                            
                            const localSignFunc = originalFactory.apply(this, arguments);
                            
                            // 包装一层，确保调用时始终使用正确的 this
                            window.G_SIGN_FUNC = function(...args) {
                                return localSignFunc.apply(window.REAL_THIS, args);
                            };
                            
                            return localSignFunc;
                        };
                    }
                    return originalDefineProperty.apply(this, arguments);
                };
            })();
        """)

        # 2. 访问目标页面触发 JS 加载
        try:
            await self._page.goto("https://pcrdfans.com/battle", wait_until="networkidle")
            # 确保劫持成功
            await self._page.wait_for_function("() => typeof window.G_SIGN_FUNC === 'function'", timeout=30000)
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

        # 3. 直接调用偷出来的闭包函数
        # 它内部会自动处理 Promise 和异步调度，所以我们这里包裹一层 evaluate 即可
        _sign = await self._page.evaluate("""
            async ([raw, nonce, transformed]) => {
                try {
                    // 调用我们劫持的局部函数引用
                    // 如果它内部有异步逻辑，我们手动加一个微小的 delay 确保结果落库
                    const result = window.G_SIGN_FUNC(raw, nonce, transformed);
                    
                    if (result) return result;
                    
                    // 如果返回是空的，尝试等待 100ms 从结果表里捞（兜底逻辑）
                    return new Promise(resolve => {
                        setTimeout(() => {
                            const table = window.SIGN_MANAGER ? window.SIGN_MANAGER['_pcrsafarifix'] : null;
                            resolve(table ? table[nonce] : null);
                        }, 100);
                    });
                } catch (e) {
                    return null;
                }
            }
        """, [raw_payload, nonce, transformed])

        if not _sign:
            return None

        payload["_sign"] = _sign
        return payload
