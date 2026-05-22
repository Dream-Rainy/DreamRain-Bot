"""HTTP 基础设施封装。

提供统一的请求入口（支持缓存/超时/重试）。
"""

from .client import HttpClient

# 全局单例客户端
http_client = HttpClient()

__all__ = ["HttpClient", "http_client"]
