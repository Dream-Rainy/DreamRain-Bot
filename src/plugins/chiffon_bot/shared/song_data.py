"""乐曲数据抽象基类 — 所有游戏 domain 的 song data 共享契约。

子类通过 ``ConfigDict(extra="allow")`` 可自由添加游戏特有字段。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SongData(BaseModel):
    """所有游戏 domain 的乐曲数据基类。

    公共字段由 shared 层直接访问（搜索、结果构建、同步等），
    游戏特有字段由子类通过 ``extra="allow"`` 扩展。
    """

    model_config = ConfigDict(extra="allow")

    id: int
    title: str
    artist: str = ""
    bpm: float = 0
    image_name: str = ""
    difficulties: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    aliases: list[str] = Field(default_factory=list)
