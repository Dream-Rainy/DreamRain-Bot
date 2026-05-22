# chiffon_bot.infra.http

这里是 HTTP 基础设施封装，用来统一：
- 超时
- 重试
- 可选磁盘缓存（diskcache）

## 使用方法

```python
from chiffon_bot.infra.http import http_client

# GET 请求（支持缓存）
data = await http_client.get_json(url, force_refresh=True)

# 带 headers 的 GET 请求
data = await http_client.get_json(url, headers={"Authorization": "Bearer xxx"})

# POST 请求
data = await http_client.post_json(url, json_data={"key": "value"})
```

## 缓存策略
- 当 `headers is None` 时，GET 默认启用缓存（7 天）
- 传 `force_refresh=True` 可跳过缓存
- POST 请求不使用缓存
