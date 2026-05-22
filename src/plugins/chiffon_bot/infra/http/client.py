from __future__ import annotations

import asyncio
import hashlib
import json
import traceback
from dataclasses import dataclass
from typing import Any, Mapping

import aiohttp
from nonebot import logger

try:
    import diskcache
except Exception:  # pragma: no cover
    traceback.print_exc()
    diskcache = None  # type: ignore


def _stable_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def build_cache_key(url: str, *, headers: Mapping[str, str] | None, params: Any | None, json_data: Any | None) -> str:
    key_parts = [url]
    if headers:
        key_parts.append(_stable_json(dict(headers)))
    if params is not None:
        key_parts.append(_stable_json(params))
    if json_data is not None:
        key_parts.append(_stable_json(json_data))
    return hashlib.md5("|".join(key_parts).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RetryPolicy:
    retries: int = 2
    base_delay: float = 0.5
    max_delay: float = 3.0

    def delays(self) -> list[float]:
        ds: list[float] = []
        for i in range(self.retries):
            delay = min(self.max_delay, self.base_delay * (2**i))
            ds.append(delay)
        return ds


class HttpClient:
    # 默认请求头，模拟真实浏览器行为
    DEFAULT_HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": "1",
        "Sec-CH-UA": '"Google Chrome";v="143", "Chromium";v="143", "Not A(Brand";v="24"',
        "Sec-CH-UA-Mobile": "?0",
        "Sec-CH-UA-Platform": '"Windows"',
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
    }
    
    def __init__(
        self,
        *,
        cache_dir: str = "/tmp/http_cache",
        cache_ttl_seconds: int = 7 * 24 * 3600,
        timeout_seconds: float = 20,
        retry: RetryPolicy | None = None,
        authorization: str | None = None,
        refresh_token: str | None = None,
    ):
        self._timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        self._retry = retry or RetryPolicy()
        self._cache_ttl = cache_ttl_seconds
        self._authorization = authorization
        self._refresh_token = refresh_token

        self._cache = None
        if diskcache is not None:
            self._cache = diskcache.Cache(cache_dir)

    async def _request_json(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Any | None = None,
        json_data: Any | None = None,
        use_cache: bool = False,
        force_refresh: bool = False,
        authorization: str | None = None,
        refresh_token: str | None = None,
    ) -> Any:
        # 合并默认请求头和自定义请求头
        merged_headers = self.DEFAULT_HEADERS.copy()
        if headers:
            merged_headers.update(headers)
        
        # 添加认证信息（请求参数优先，然后是实例默认值）
        auth = authorization or self._authorization
        if auth:
            merged_headers["Authorization"] = auth
        
        # 根据 URL 设置 Referer（如果是 lxns.net 域名）
        if "lxns.net" in url and "Referer" not in merged_headers:
            merged_headers["Referer"] = "https://maimai.lxns.net"
        
        cache_key = build_cache_key(url, headers=headers, params=params, json_data=json_data)
        if use_cache and not force_refresh and self._cache is not None and cache_key in self._cache:
            logger.debug(f"HTTP 缓存命中: {method} {url}")
            return self._cache[cache_key]

        last_exc: Exception | None = None
        delays = [0.0] + self._retry.delays()
        for attempt, delay in enumerate(delays, 1):
            if delay:
                await asyncio.sleep(delay)
            try:
                logger.debug(f"HTTP 请求: {method} {url} (尝试 {attempt}/{len(delays)})")
                # 准备 cookies
                cookies = {}
                token = refresh_token or self._refresh_token
                if token:
                    cookies["refresh_token"] = token
                
                async with aiohttp.ClientSession(timeout=self._timeout, trust_env=True) as session:
                    async with session.request(method, url, headers=merged_headers, params=params, json=json_data, cookies=cookies) as resp:
                        resp.raise_for_status()
                        content_type = resp.headers.get("Content-Type", "").lower()
                        # 扩展兼容 text/plain、application/javascript、+json 等返回类型
                        should_try_json = any(
                            key in content_type
                            for key in ["json", "+json", "javascript", "text/plain"]
                        )

                        data: Any
                        if should_try_json:
                            try:
                                data = await resp.json()
                            except Exception:
                                # 退回文本再尝试 json 解析，最后原样文本
                                raw_text = await resp.text()
                                try:
                                    data = json.loads(raw_text)
                                except Exception:
                                    data = raw_text
                        else:
                            # 默认路径，保持原行为
                            data = await resp.json()

                        if use_cache and self._cache is not None:
                            self._cache.set(cache_key, data, self._cache_ttl)
                        logger.debug(f"HTTP 请求成功: {method} {url} (status: {resp.status})")
                        return data
            except aiohttp.ClientResponseError as e:
                # traceback.print_exc()
                # 4xx 客户端错误不重试，直接抛出
                if 400 <= e.status < 500:
                    logger.error(f"HTTP 客户端错误 (不重试): {method} {url} - {e.status} {e.message}")
                    raise
                # 5xx 服务器错误继续重试
                logger.warning(f"HTTP 请求失败 (尝试 {attempt}/{len(delays)}): {method} {url} - {type(e).__name__}: {e}")
                last_exc = e
                continue
            except Exception as e:  # noqa: BLE001
                # traceback.print_exc()
                logger.warning(f"HTTP 请求失败 (尝试 {attempt}/{len(delays)}): {method} {url} - {type(e).__name__}: {e}")
                last_exc = e
                continue

        logger.error(f"HTTP 所有重试失败: {method} {url} - {last_exc}")
        raise last_exc or RuntimeError("http request failed")

    async def get_json(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Any | None = None,
        json_data: Any | None = None,
        force_refresh: bool = False,
        cache: bool = True,
        authorization: str | None = None,
        refresh_token: str | None = None,
    ) -> Any:
        # 兼容旧逻辑：只有在 headers 为 None 时默认启用缓存
        use_cache = cache and (headers is None)
        return await self._request_json(
            "GET",
            url,
            headers=headers,
            params=params,
            json_data=json_data,
            use_cache=use_cache,
            force_refresh=force_refresh,
            authorization=authorization,
            refresh_token=refresh_token,
        )

    async def post_json(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Any | None = None,
        json_data: Any | None = None,
        authorization: str | None = None,
        refresh_token: str | None = None,
    ) -> Any:
        return await self._request_json(
            "POST",
            url,
            headers=headers,
            params=params,
            json_data=json_data,
            use_cache=False,
            force_refresh=False,
            authorization=authorization,
            refresh_token=refresh_token,
        )

    async def get_bytes(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Any | None = None,
    ) -> bytes:
        """下载二进制内容（如图片）。"""
        last_exc: Exception | None = None
        delays = [0.0] + self._retry.delays()
        for attempt, delay in enumerate(delays, 1):
            if delay:
                await asyncio.sleep(delay)
            try:
                logger.debug(f"HTTP 请求: GET {url} (尝试 {attempt}/{len(delays)})")
                async with aiohttp.ClientSession(timeout=self._timeout) as session:
                    async with session.get(url, headers=headers, params=params) as resp:
                        resp.raise_for_status()
                        data = await resp.read()
                        logger.debug(f"HTTP 请求成功: GET {url} (status: {resp.status}, size: {len(data)} bytes)")
                        return data
            except Exception as e:  # noqa: BLE001
                traceback.print_exc()
                logger.warning(f"HTTP 请求失败 (尝试 {attempt}/{len(delays)}): GET {url} - {type(e).__name__}: {e}")
                last_exc = e
                continue

        logger.error(f"HTTP 所有重试失败: GET {url} - {last_exc}")
        raise last_exc or RuntimeError("http request failed")
