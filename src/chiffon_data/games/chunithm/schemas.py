"""CHUNITHM 乐曲数据模型。"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from ...core.song import SongData, SongSheet


class ChuniSongSheet(SongSheet):
    """CHUNITHM 乐曲谱面信息（合并 LXNS 和 arcade-songs 数据）。"""

    type: str  # std, we
    difficulty: str  # BASIC, ADVANCED, EXPERT, MASTER, ULTIMA, WE 汉字
    level: str  # 显示等级


class ChuniSongData(SongData[ChuniSongSheet]):
    """CHUNITHM 乐曲完整数据模型（合并 arcade-songs 和 LXNS 数据）。"""

    genre: str = ""
    version: int | None = None
    release_date: str = ""
    comment: str = ""
    song_id: str | None = Field(None, alias="songId")

    difficulties: dict[str, list[ChuniSongSheet]] = Field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ChuniSongData":
        """从字典创建实例（兼容 camelCase 键名）。"""
        return cls.model_validate(data)
