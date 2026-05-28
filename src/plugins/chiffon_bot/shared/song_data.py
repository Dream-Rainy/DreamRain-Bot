"""乐曲数据抽象基类 — 所有游戏 domain 的 song data 共享契约。

子类通过 ``ConfigDict(extra="allow")`` 可自由添加游戏特有字段。
"""

from __future__ import annotations

from typing import Generic, TypeVar
from pydantic import BaseModel, ConfigDict, Field


class SongSheet(BaseModel):
    """所有游戏 domain 的谱面数据基类。

    公共字段由 shared 层直接访问（搜索、结果构建、同步等），
    游戏特有字段由子类通过 ``extra="allow"`` 扩展。
    """
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    type: str
    difficulty: str
    level: str
    level_value: float | None = Field(None, alias="levelValue")
    internal_level_value: float | None = Field(None, alias="internalLevelValue")
    internal_level_value_new: float | None = Field(None, alias="internalLevelValueNew")
    note_designer: str | None = Field(None, alias="noteDesigner")
    note_counts: dict | None = Field(None, alias="noteCounts")
    regions: dict[str, bool] | None = None


SongSheetT = TypeVar("SongSheetT", bound=SongSheet)


class SongData(BaseModel, Generic[SongSheetT]):
    """所有游戏 domain 的乐曲数据基类。

    公共字段由 shared 层直接访问（搜索、结果构建、同步等），
    游戏特有字段由子类通过 ``extra="allow"`` 扩展。
    """

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    id: int
    title: str
    artist: str = ""
    bpm: float = 0
    image_name: str = ""
    difficulties: dict[str, list[SongSheetT]] = Field(default_factory=dict)
    aliases: list[str] = Field(default_factory=list)

    # 各游戏域共有的可选字段
    rights: str | None = None
    is_new: bool = False
    is_locked: bool = False
