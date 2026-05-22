"""Maimai 地图XML解析器：解析Map.xml和MapTreasure.xml文件。"""

import os
import xml.etree.ElementTree as ET
from pathlib import Path
from nonebot import logger

from ..schemas import MapData, MapTreasureData, MapTreasureExData, MapBonusMusicData


def parse_id_str_element(element: ET.Element | None) -> tuple[int | None, str | None]:
    """解析包含id和str子元素的元素。
    
    Args:
        element: XML元素
        
    Returns:
        (id值, str值) 元组
    """
    if element is None:
        return None, None
    
    id_elem = element.find("id")
    str_elem = element.find("str")
    
    id_val = None
    if id_elem is not None and id_elem.text:
        try:
            id_val = int(id_elem.text)
        except ValueError:
            pass
    
    str_val = str_elem.text if str_elem is not None and str_elem.text else None
    
    return id_val, str_val


def parse_map_bonus_music_xml(xml_path: str | Path) -> MapBonusMusicData | None:
    """解析MapBonusMusic.xml文件。
    
    Args:
        xml_path: XML文件路径
        
    Returns:
        MapBonusMusicData实例，解析失败返回None
    """
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
        
        # 解析基本信息
        data_name = root.findtext("dataName", "")
        
        # 解析name元素
        name_elem = root.find("name")
        bonus_music_id, bonus_music_name = parse_id_str_element(name_elem)
        
        # 从bonus_music_name中提取map名称（去除"ボーナス曲"后缀）
        map_name = None
        if bonus_music_name:
            # 提取"ボーナス曲"前的部分作为map名称
            bonus_suffix = "ボーナス曲"
            if bonus_suffix in bonus_music_name:
                map_name = bonus_music_name.split(bonus_suffix)[0].strip()
        
        # 解析MusicIds列表
        music_ids = []
        music_names = {}  # music_id -> music_name 映射
        music_ids_elem = root.find("MusicIds")
        if music_ids_elem is not None:
            list_elem = music_ids_elem.find("list")
            if list_elem is not None:
                for string_id_elem in list_elem.findall("StringID"):
                    music_id, music_name = parse_id_str_element(string_id_elem)
                    if music_id:
                        music_ids.append(music_id)
                        if music_name:
                            music_names[music_id] = music_name
        
        return MapBonusMusicData(
            dataName=data_name,
            bonusMusicId=bonus_music_id or 0,
            bonusMusicName=bonus_music_name or "",
            mapName=map_name,
            MusicIds=music_ids,
            MusicNames=music_names,
        )
    except Exception as e:
        logger.error(f"解析MapBonusMusic XML失败 ({xml_path}): {e}")
        return None


def parse_map_treasure_xml(xml_path: str | Path) -> MapTreasureData | None:
    """解析MapTreasure.xml文件。
    
    Args:
        xml_path: XML文件路径
        
    Returns:
        MapTreasureData实例，解析失败返回None
    """
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
        
        # 解析基本信息
        data_name = root.findtext("dataName", "")
        item_id_text = root.findtext("itemID", "0")
        item_id = int(item_id_text) if item_id_text else 0
        
        # 解析name元素
        name_elem = root.find("name")
        _, treasure_name = parse_id_str_element(name_elem)
        
        # 解析TreasureType
        treasure_type = root.findtext("TreasureType", "")
        
        # 解析各类ID和名称
        character_id, character_name = parse_id_str_element(root.find("CharacterId"))
        music_id, music_name = parse_id_str_element(root.find("MusicId"))
        name_plate_id, name_plate_name = parse_id_str_element(root.find("NamePlate"))
        frame_id, frame_name = parse_id_str_element(root.find("Frame"))
        title_id, title_name = parse_id_str_element(root.find("Title"))
        icon_id, icon_name = parse_id_str_element(root.find("Icon"))
        challenge_id, challenge_name = parse_id_str_element(root.find("Challenge"))
        gate_id, gate_name = parse_id_str_element(root.find("Gate"))
        key_id, key_name = parse_id_str_element(root.find("Key"))
        
        # 解析Numeric
        numeric_text = root.findtext("Numeric")
        numeric = int(numeric_text) if numeric_text else None
        
        return MapTreasureData(
            dataName=data_name,
            itemID=item_id,
            treasureName=treasure_name or "",
            TreasureType=treasure_type,
            characterId=character_id,
            characterName=character_name,
            musicId=music_id,
            musicName=music_name,
            Numeric=numeric,
            namePlateId=name_plate_id,
            namePlateName=name_plate_name,
            frameId=frame_id,
            frameName=frame_name,
            titleId=title_id,
            titleName=title_name,
            iconId=icon_id,
            iconName=icon_name,
            challengeId=challenge_id,
            challengeName=challenge_name,
            gateId=gate_id,
            gateName=gate_name,
            keyId=key_id,
            keyName=key_name,
        )
    except Exception as e:
        logger.error(f"解析MapTreasure XML失败 ({xml_path}): {e}")
        return None


def parse_map_xml(xml_path: str | Path, map_treasure_base_dir: str | Path | None = None) -> MapData | None:
    """解析Map.xml文件并关联MapTreasure数据。
    
    Args:
        xml_path: Map.xml文件路径
        map_treasure_base_dir: MapTreasure文件夹基础路径（可选）
        
    Returns:
        MapData实例，解析失败返回None
    """
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
        
        # 解析基本信息
        data_name = root.findtext("dataName", "")
        
        # 解析name元素
        name_elem = root.find("name")
        map_id, map_name = parse_id_str_element(name_elem)
        
        # 解析布尔值
        is_collabo_text = root.findtext("IsCollabo", "false")
        is_collabo = is_collabo_text.lower() == "true"
        
        is_infinity_text = root.findtext("IsInfinity", "false")
        is_infinity = is_infinity_text.lower() == "true"
        
        # 解析各类ID和名称
        island_id, island_name = parse_id_str_element(root.find("IslandId"))
        color_id, color_name = parse_id_str_element(root.find("ColorId"))
        bonus_music_id, bonus_music_name = parse_id_str_element(root.find("BonusMusicId"))
        open_event_id, open_event_name = parse_id_str_element(root.find("OpenEventId"))
        net_open_name_id, net_open_name = parse_id_str_element(root.find("netOpenName"))
        
        # 解析BonusMusicMagnification
        bonus_music_mag_text = root.findtext("BonusMusicMagnification")
        bonus_music_mag = int(bonus_music_mag_text) if bonus_music_mag_text else None
        
        # 解析TreasureExDatas
        treasures = []
        treasure_ex_datas = root.find("TreasureExDatas")
        if treasure_ex_datas is not None:
            for treasure_elem in treasure_ex_datas.findall("MapTreasureExData"):
                distance_text = treasure_elem.findtext("Distance", "0")
                distance = int(distance_text) if distance_text else 0
                
                flag = treasure_elem.findtext("Flag", "")
                
                sub_param1_text = treasure_elem.findtext("SubParam1", "-1")
                sub_param1 = int(sub_param1_text) if sub_param1_text else -1
                
                sub_param2_text = treasure_elem.findtext("SubParam2", "-1")
                sub_param2 = int(sub_param2_text) if sub_param2_text else -1
                
                treasure_id, treasure_name = parse_id_str_element(treasure_elem.find("TreasureId"))
                
                # 尝试从MapTreasure文件夹中获取详细信息
                if map_treasure_base_dir and treasure_id:
                    treasure_detail = load_map_treasure_by_id(treasure_id, map_treasure_base_dir)
                    if treasure_detail:
                        # 从详细信息中提取名称
                        treasure_name = treasure_detail.treasure_name
                
                treasures.append(MapTreasureExData(
                    Distance=distance,
                    Flag=flag,
                    SubParam1=sub_param1,
                    SubParam2=sub_param2,
                    TreasureId=treasure_id or 0,
                    treasure_name=treasure_name,
                ))
        
        return MapData(
            dataName=data_name,
            mapId=map_id or 0,
            mapName=map_name or "",
            IsCollabo=is_collabo,
            IsInfinity=is_infinity,
            islandId=island_id,
            islandName=island_name,
            colorId=color_id,
            colorName=color_name,
            bonusMusicId=bonus_music_id,
            bonusMusicName=bonus_music_name,
            BonusMusicMagnification=bonus_music_mag,
            openEventId=open_event_id,
            openEventName=open_event_name,
            netOpenNameId=net_open_name_id,
            netOpenName=net_open_name,
            TreasureExDatas=treasures,
        )
    except Exception as e:
        logger.error(f"解析Map XML失败 ({xml_path}): {e}")
        return None


def load_map_treasure_by_id(treasure_id: int, base_dir: str | Path) -> MapTreasureData | None:
    """根据treasure_id加载对应的MapTreasure.xml文件。
    
    Args:
        treasure_id: 奖励ID
        base_dir: MapTreasure文件夹基础路径
        
    Returns:
        MapTreasureData实例，未找到返回None
    """
    base_path = Path(base_dir)
    if not base_path.exists():
        return None
    
    # 查找MapTreasure{treasure_id}文件夹
    treasure_folder = base_path / f"MapTreasure{treasure_id}"
    if not treasure_folder.exists() or not treasure_folder.is_dir():
        return None
    
    # 查找MapTreasure.xml文件
    treasure_xml = treasure_folder / "MapTreasure.xml"
    if not treasure_xml.exists():
        return None
    
    return parse_map_treasure_xml(treasure_xml)


def scan_map_directory(map_base_dir: str | Path, map_treasure_base_dir: str | Path | None = None) -> dict[int, MapData]:
    """递归扫描指定目录，解析所有Map.xml文件。
    
    Args:
        map_base_dir: Map文件夹基础路径
        map_treasure_base_dir: MapTreasure文件夹基础路径（可选）
        
    Returns:
        {map_id: MapData} 字典
    """
    result = {}
    
    base_path = Path(map_base_dir)
    if not base_path.exists() or not base_path.is_dir():
        logger.warning(f"Map目录不存在或不可访问: {map_base_dir}")
        return result
    
    logger.info(f"开始扫描Map目录: {map_base_dir}")
    
    # 递归查找所有Map.xml文件
    for map_xml_path in base_path.rglob("Map.xml"):
        logger.debug(f"发现Map.xml文件: {map_xml_path}")
        map_data = parse_map_xml(map_xml_path, map_treasure_base_dir)
        if map_data:
            result[map_data.map_id] = map_data
            logger.debug(f"成功解析Map: {map_data.map_name} (ID: {map_data.map_id})")
    
    logger.info(f"Map目录扫描完成，共解析 {len(result)} 个地图")
    return result


def extract_music_ids_from_maps(
    maps: dict[int, MapData],
    map_treasure_base_dir: str | Path | None = None,
    map_bonus_music_base_dir: str | Path | None = None,
) -> dict[int, int]:
    """从地图数据中提取music_id到map_id的映射。
    
    从两个来源收集music_id：
    1. Map的bonus_music_id字段（仅bonus_music_id本身，不包括MapBonusMusic中的其他乐曲）
    2. MapTreasure中的music_id（Map的奖励中的乐曲）
    
    注意：MapBonusMusic中的乐曲列表不会被自动关联到Map，
    因为这些乐曲不一定从属于该区域，它们只是可能的bonus候选。
    
    Args:
        maps: 地图数据字典
        map_treasure_base_dir: MapTreasure文件夹基础路径（可选）
        map_bonus_music_base_dir: MapBonusMusic文件夹基础路径（未使用，保留参数兼容性）
        
    Returns:
        {music_id: map_id} 字典
    """
    music_to_map = {}
    
    for map_id, map_data in maps.items():
        # 来源1: Map的bonus_music_id字段（仅ID本身）
        if map_data.bonus_music_id and map_data.bonus_music_id > 0:
            music_to_map[map_data.bonus_music_id] = map_id
            logger.debug(f"从Map.bonus_music_id发现关联: music_id={map_data.bonus_music_id} -> map_id={map_id}")
        
        # 来源2: 从每个奖励中提取music_id
        for treasure in map_data.treasures:
            if treasure.treasure_id:
                # 加载完整的treasure数据
                treasure_detail = None
                if map_treasure_base_dir:
                    treasure_detail = load_map_treasure_by_id(treasure.treasure_id, map_treasure_base_dir)
                
                if treasure_detail and treasure_detail.music_id and treasure_detail.music_id > 0:
                    music_to_map[treasure_detail.music_id] = map_id
                    logger.debug(f"从MapTreasure发现关联: music_id={treasure_detail.music_id} -> map_id={map_id}")
    
    logger.info(f"从地图中提取到 {len(music_to_map)} 个music_id关联")
    return music_to_map


def scan_map_treasure_directory(map_treasure_base_dir: str | Path) -> dict[int, MapTreasureData]:
    """递归扫描指定目录，解析所有MapTreasure.xml文件。
    
    Args:
        map_treasure_base_dir: MapTreasure文件夹基础路径
        
    Returns:
        {treasure_id: MapTreasureData} 字典
    """
    result = {}
    
    base_path = Path(map_treasure_base_dir)
    if not base_path.exists() or not base_path.is_dir():
        logger.warning(f"MapTreasure目录不存在或不可访问: {map_treasure_base_dir}")
        return result
    
    logger.info(f"开始扫描MapTreasure目录: {map_treasure_base_dir}")
    
    # 递归查找所有MapTreasure.xml文件
    for treasure_xml_path in base_path.rglob("MapTreasure.xml"):
        logger.debug(f"发现MapTreasure.xml文件: {treasure_xml_path}")
        treasure_data = parse_map_treasure_xml(treasure_xml_path)
        if treasure_data and treasure_data.item_id:
            result[treasure_data.item_id] = treasure_data
            logger.debug(f"成功解析MapTreasure: {treasure_data.treasure_name} (ID: {treasure_data.item_id})")
    
    logger.info(f"MapTreasure目录扫描完成，共解析 {len(result)} 个奖励")
    return result


def scan_map_bonus_music_directory(map_bonus_music_base_dir: str | Path) -> dict[int, MapBonusMusicData]:
    """递归扫描指定目录，解析所有MapBonusMusic.xml文件。
    
    Args:
        map_bonus_music_base_dir: MapBonusMusic文件夹基础路径
        
    Returns:
        {bonus_music_id: MapBonusMusicData} 字典
    """
    result = {}
    
    base_path = Path(map_bonus_music_base_dir)
    if not base_path.exists() or not base_path.is_dir():
        logger.warning(f"MapBonusMusic目录不存在或不可访问: {map_bonus_music_base_dir}")
        return result
    
    logger.info(f"开始扫描MapBonusMusic目录: {map_bonus_music_base_dir}")
    
    # 递归查找所有MapBonusMusic.xml文件
    for bonus_music_xml_path in base_path.rglob("MapBonusMusic.xml"):
        logger.debug(f"发现MapBonusMusic.xml文件: {bonus_music_xml_path}")
        bonus_music_data = parse_map_bonus_music_xml(bonus_music_xml_path)
        if bonus_music_data and bonus_music_data.bonus_music_id:
            result[bonus_music_data.bonus_music_id] = bonus_music_data
            logger.debug(f"成功解析MapBonusMusic: {bonus_music_data.bonus_music_name} (ID: {bonus_music_data.bonus_music_id})")
    
    logger.info(f"MapBonusMusic目录扫描完成，共解析 {len(result)} 个奖励音乐")
    return result
