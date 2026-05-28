from __future__ import annotations

import asyncio
from typing import Any

import aiohttp
from nonebot import get_plugin_config, logger

from ...config import Config

plugin_config = get_plugin_config(Config)


class SseRelayClient:
    """SSE 中继客户端：连接公网 Relay，监听 OAuth 回调事件。"""

    def __init__(self) -> None:
        self._pending: dict[str, asyncio.Future[str]] = {}
        self._task: asyncio.Task[None] | None = None
        self._running = False

    @property
    def relay_url(self) -> str:
        return plugin_config.lxns_oauth_relay_url

    @property
    def relay_token(self) -> str:
        return plugin_config.lxns_oauth_relay_token

    @property
    def is_connected(self) -> bool:
        return self._running

    def register(self, state: str) -> asyncio.Future[str]:
        """注册一个 state 等待 Relay 推送授权码。返回 awaitable future。"""
        future: asyncio.Future[str] = asyncio.get_event_loop().create_future()
        self._pending[state] = future
        return future

    def unregister(self, state: str) -> None:
        self._pending.pop(state, None)

    def _event_received(self, data: dict[str, Any]) -> None:
        state = data.get("state")
        code = data.get("code")
        if state and code and state in self._pending:
            future = self._pending.pop(state)
            if not future.done():
                future.set_result(code)

    async def start(self) -> None:
        if not self.relay_url or not self.relay_token:
            logger.warning("[sse_client] Relay URL 或 token 未配置，SSE 客户端不会启动")
            return

        self._running = True
        self._task = asyncio.create_task(self._connect_loop())
        logger.info(f"[sse_client] 已启动，连接 {self.relay_url}")

    async def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        # 取消所有等待中的 future
        for state, future in list(self._pending.items()):
            if not future.done():
                future.cancel()
            del self._pending[state]
        logger.info("[sse_client] 已停止")

    async def _connect_loop(self) -> None:
        url = f"{self.relay_url.rstrip('/')}/events?token={self.relay_token}"
        backoff = 1

        while self._running:
            try:
                timeout = aiohttp.ClientTimeout(total=0, sock_read=60)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(url) as resp:
                        if resp.status != 200:
                            logger.warning(f"[sse_client] Relay 返回 {resp.status}，{backoff}s 后重试")
                            await asyncio.sleep(backoff)
                            backoff = min(backoff * 2, 60)
                            continue

                        backoff = 1  # 连接成功，重置退避
                        logger.info("[sse_client] SSE 连接已建立")
                        buf = ""
                        async for line_bytes, _ in resp.content.iter_chunks():
                            if not self._running:
                                break
                            buf += line_bytes.decode("utf-8", errors="replace")
                            while "\n" in buf:
                                line, buf = buf.split("\n", 1)
                                line = line.strip()
                                if line.startswith("data: "):
                                    try:
                                        import json

                                        data = json.loads(line[6:])
                                        self._event_received(data)
                                    except Exception:
                                        logger.warning(f"[sse_client] 无法解析事件: {line}")
            except asyncio.CancelledError:
                break
            except Exception:
                logger.warning(f"[sse_client] 连接断开，{backoff}s 后重连")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)


sse_client = SseRelayClient()

__all__ = ["SseRelayClient", "sse_client"]
