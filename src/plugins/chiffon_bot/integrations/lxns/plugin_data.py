"""LXNS 曲库/配置缓存容器。

这是一个共享的、进程内的缓存对象：启动时由插件初始化填充。
领域层（domains）可以读取它来渲染/查询，但不应在这里做任何网络请求。
"""

from __future__ import annotations

from typing import Any


class PluginData:
    headers: dict[str, str] = {}
    data_version: dict[str, Any] = {}
    # 轻量乐曲索引：仅保留 song_id -> title，完整曲目数据按需从数据库加载
    mai_song_index: dict[int, str] = {}
    chuni_song_index: dict[int, str] = {}
    # Deprecated: 完整曲库不再作为启动常驻缓存使用，仅保留兼容旧调用点。
    mai_song_data: dict[int, Any] = {}
    chuni_song_data: dict[int, Any] = {}
    # 别名数据缓存（已废弃：别名现已直接存储在 song_data 的 aliases 字段中）
    mai_alias_data: dict[int, dict[str, str | list[str]]] = {}
    chuni_alias_data: dict = {}
    # 收藏信息缓存（奖杯、称号等）
    mai_collections_data: dict[int, list[dict]] = {}


plugin_data = PluginData()

__all__ = ["PluginData", "plugin_data"]
