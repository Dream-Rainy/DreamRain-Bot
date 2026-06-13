"""Maimai 乐曲数据模型定义。"""

from typing import Any
from pydantic import BaseModel, ConfigDict, Field

from ...core.song import SongData, SongSheet


class MapTreasureExData(BaseModel):
    """地图奖励扩展数据（来自 Map.xml）。"""
    
    distance: int = Field(alias="Distance")  # 距离
    flag: str = Field(alias="Flag")  # 标志（DispCharacter, End等）
    sub_param1: int = Field(alias="SubParam1")  # 子参数1
    sub_param2: int = Field(alias="SubParam2")  # 子参数2
    treasure_id: int = Field(alias="TreasureId")  # 奖励ID
    treasure_name: str | None = None  # 奖励名称（从TreasureId的str获取）
    
    class Config:
        populate_by_name = True


class MapData(BaseModel):
    """Maimai 地图数据（来自 Map.xml）。"""
    
    data_name: str = Field(alias="dataName")  # 数据名称
    map_id: int = Field(alias="mapId")  # 地图ID（从name.id获取）
    map_name: str = Field(alias="mapName")  # 地图名称（从name.str获取）
    is_collabo: bool = Field(False, alias="IsCollabo")  # 是否联动
    is_infinity: bool = Field(False, alias="IsInfinity")  # 是否无限
    island_id: int | None = Field(None, alias="islandId")  # 岛屿ID
    island_name: str | None = Field(None, alias="islandName")  # 岛屿名称
    color_id: int | None = Field(None, alias="colorId")  # 颜色ID
    color_name: str | None = Field(None, alias="colorName")  # 颜色名称
    bonus_music_id: int | None = Field(None, alias="bonusMusicId")  # 奖励音乐ID
    bonus_music_name: str | None = Field(None, alias="bonusMusicName")  # 奖励音乐名称
    bonus_music_magnification: int | None = Field(None, alias="BonusMusicMagnification")  # 奖励音乐倍率
    open_event_id: int | None = Field(None, alias="openEventId")  # 开放活动ID
    open_event_name: str | None = Field(None, alias="openEventName")  # 开放活动名称
    net_open_name_id: int | None = Field(None, alias="netOpenNameId")  # 网络开放名称ID
    net_open_name: str | None = Field(None, alias="netOpenName")  # 网络开放名称
    treasures: list[MapTreasureExData] = Field(default_factory=list, alias="TreasureExDatas")  # 奖励列表
    
    class Config:
        populate_by_name = True


class MapBonusMusicData(BaseModel):
    """Maimai 地图奖励音乐数据（来自 MapBonusMusic.xml）。"""
    
    data_name: str = Field(alias="dataName")  # 数据名称
    bonus_music_id: int = Field(alias="bonusMusicId")  # 奖励音乐ID（从name.id获取）
    bonus_music_name: str = Field(alias="bonusMusicName")  # 奖励音乐名称（从name.str获取）
    map_name: str | None = Field(None, alias="mapName")  # 地图名称（从bonus_music_name中提取，去除"ボーナス曲"后缀）
    music_ids: list[int] = Field(default_factory=list, alias="MusicIds")  # 包含的音乐ID列表
    music_names: dict[int, str] = Field(default_factory=dict, alias="MusicNames")  # music_id -> music_name 映射
    
    class Config:
        populate_by_name = True


class MapTreasureData(BaseModel):
    """Maimai 地图奖励数据（来自 MapTreasure.xml）。"""
    
    data_name: str = Field(alias="dataName")  # 数据名称
    item_id: int = Field(alias="itemID")  # 物品ID
    treasure_name: str = Field(alias="treasureName")  # 奖励名称（从name.str获取）
    treasure_type: str = Field(alias="TreasureType")  # 奖励类型
    character_id: int | None = Field(None, alias="characterId")  # 角色ID
    character_name: str | None = Field(None, alias="characterName")  # 角色名称
    music_id: int | None = Field(None, alias="musicId")  # 音乐ID
    music_name: str | None = Field(None, alias="musicName")  # 音乐名称
    numeric: int | None = Field(None, alias="Numeric")  # 数值
    name_plate_id: int | None = Field(None, alias="namePlateId")  # 姓名牌ID
    name_plate_name: str | None = Field(None, alias="namePlateName")  # 姓名牌名称
    frame_id: int | None = Field(None, alias="frameId")  # 框架ID
    frame_name: str | None = Field(None, alias="frameName")  # 框架名称
    title_id: int | None = Field(None, alias="titleId")  # 称号ID
    title_name: str | None = Field(None, alias="titleName")  # 称号名称
    icon_id: int | None = Field(None, alias="iconId")  # 图标ID
    icon_name: str | None = Field(None, alias="iconName")  # 图标名称
    challenge_id: int | None = Field(None, alias="challengeId")  # 挑战ID
    challenge_name: str | None = Field(None, alias="challengeName")  # 挑战名称
    gate_id: int | None = Field(None, alias="gateId")  # 门ID
    gate_name: str | None = Field(None, alias="gateName")  # 门名称
    key_id: int | None = Field(None, alias="keyId")  # 钥匙ID
    key_name: str | None = Field(None, alias="keyName")  # 钥匙名称
    
    class Config:
        populate_by_name = True


class MaiSongSheet(SongSheet):
    """Maimai 乐曲谱面信息（来自 dxrating）。"""

    type: str  # dx, std, utage
    difficulty: str  # basic, advanced, expert, master, remaster
    level: str  # 显示等级，如 "13+"
    internal_level: str | None = Field(None, alias="internalLevel")
    region_overrides: dict[str, Any] | None = Field(None, alias="regionOverrides")
    is_special: bool = Field(False, alias="isSpecial")
    is_buddy: bool | None = Field(False, alias="isBuddy")
    version: str | None = None
    internal_id: int | None = Field(None, alias="internalId")


class MaiSongData(SongData[MaiSongSheet]):
    """Maimai 乐曲完整数据模型（合并 dxrating 和 LXNS 数据）。"""

    model_config = ConfigDict(populate_by_name=True)

    category: str | None = None
    version: str | None = None
    release_date: str | None = Field(None, alias="releaseDate")
    comment: str | None = None

    mai_map: str | None = Field(None, alias="maiMap")

    difficulties: dict[str, list[MaiSongSheet]] = Field(default_factory=dict)

    # 收藏信息（奖杯、称号等）
    collections: list[dict[str, Any]] = Field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典格式（用于兼容现有代码）。"""
        return self.model_dump(by_alias=False, exclude_none=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MaiSongData":
        """从字典创建实例。"""
        return cls.model_validate(data)
