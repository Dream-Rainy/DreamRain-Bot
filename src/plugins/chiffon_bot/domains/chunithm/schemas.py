"""CHUNITHM 乐曲数据模型。"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from ...shared.song_data import SongData


class ChuniSongData(SongData):
    """CHUNITHM 乐曲完整数据模型（合并 arcade-songs 和 LXNS 数据）。"""

    # CHUNITHM 特有字段
    genre: str = ""  # 曲风分类
    version: int | None = None  # 版本号（LXNS int）
    release_date: str = ""  # 发布日期
    is_new: bool = False  # 是否新曲
    is_locked: bool = False  # 是否锁定
    comment: str = ""  # 备注
    rights: str | None = None  # 版权信息
    song_id: str | None = Field(None, alias="songId")  # arcade 内部 songId

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ChuniSongData":
        """从字典创建实例（兼容 camelCase 键名）。"""
        return cls.model_validate(data)
