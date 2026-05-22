from tortoise import fields
from tortoise.models import Model


QQ_PLATFORM = "qq"


class User(Model):
    """主用户表：仅存全局唯一 user id + 可序列化 profile"""

    id = fields.IntField(pk=True)
    profile_json = fields.JSONField(default=dict)

    class Meta(Model.Meta):
        table = "users"


class UserAccount(Model):
    """用户账号表：一个用户可绑定多个平台/多个账号；账号信息 JSON 化"""

    id = fields.IntField(pk=True)

    user: fields.ForeignKeyRelation[User] = fields.ForeignKeyField(
        "models.User",
        related_name="accounts",
        on_delete=fields.CASCADE,
        index=True,
    )

    platform = fields.CharField(max_length=32, index=True)
    account_name = fields.CharField(max_length=64, null=True, default="User Account")
    account_key = fields.CharField(max_length=128)
    is_default = fields.BooleanField(default=False, index=True)
    schema_version = fields.IntField(default=1)
    account_json = fields.JSONField(default=dict)

    class Meta(Model.Meta):
        table = "user_accounts"
        unique_together = (("platform", "account_key"),)
        indexes = (
            ("user_id", "platform"),
            ("user_id", "platform", "is_default"),
            ("platform", "account_key"),
        )


class GameProfile(Model):
    """游戏侧资料单独存表，并与某个 UserAccount 绑定。"""

    id = fields.IntField(pk=True)

    account: fields.OneToOneRelation[UserAccount] = fields.OneToOneField(
        "models.UserAccount",
        related_name="game_profile",
        on_delete=fields.CASCADE,
        index=True,
    )

    platform = fields.CharField(max_length=32, index=True)

    maimai_name = fields.CharField(max_length=64, null=True)
    maimai_friend_code = fields.CharField(max_length=32, null=True, index=True)

    chunithm_name = fields.CharField(max_length=64, null=True)
    chunithm_friend_code = fields.CharField(max_length=32, null=True, index=True)

    updated_at = fields.DatetimeField(auto_now=True)

    class Meta(Model.Meta):
        table = "game_profiles"


async def get_user_by_qq(qq: str) -> User | None:
    """通过 QQ 号定位用户（返回 User 或 None）。"""

    link = await UserAccount.get_or_none(platform=QQ_PLATFORM, account_key=qq).prefetch_related("user")
    return link.user if link else None


# async def get_default_account_by_qq(qq: str) -> UserAccount | None:
#     """通过 QQ 号定位该用户在 QQ 平台的默认账号（返回 UserAccount 或 None）。"""

#     link = await UserAccount.get_or_none(platform=QQ_PLATFORM, account_key=qq)
#     if link is None:
#         return None

#     return await UserAccount.get_or_none(user_id=link.user_id, platform=QQ_PLATFORM, is_default=True)


async def ensure_user_by_qq(qq: str) -> User:
    """通过 QQ 号定位/创建用户（不存在则创建 User 与 QQ 绑定记录）。"""

    user = await get_user_by_qq(qq)
    if user is not None:
        return user

    user = await User.create(profile_json={})
    await UserAccount.create(
        user=user,
        platform=QQ_PLATFORM,
        account_key=qq,
        account_name=f"QQ_{qq}",
        is_default=True,
        schema_version=1,
        account_json={"qq": qq},
    )
    return user


class Event(Model):
    """赛事表：存储赛事信息"""

    id = fields.IntField(pk=True)
    name = fields.CharField(max_length=128, unique=True)
    group_id = fields.CharField(max_length=32, null=True, index=True)  # 主群号（拥有所有权限）
    extra_group_ids = fields.JSONField(default=list)  # 额外绑定的群号列表（仅可查看排行榜）
    start_time = fields.DatetimeField()
    end_time = fields.DatetimeField()
    songs = fields.JSONField(default=list)  # 课题曲列表，格式：[{"id": 689, "song_name": "Credits", "level": "13", "level_index": 2, "type": "standard"}, ...]
    created_by: fields.ForeignKeyNullableRelation[User] = fields.ForeignKeyField(
        "models.User",
        related_name="created_events",
        on_delete=fields.SET_NULL,
        null=True,
    )
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta(Model.Meta):
        table = "events"


class Team(Model):
    """队伍表：存储队伍信息"""

    id = fields.IntField(pk=True)
    name = fields.CharField(max_length=128, unique=True)
    real_name = fields.CharField(max_length=128, null=True)  # 队伍真实名称（显示用）
    icon = fields.TextField(null=True)  # 队伍图标（base64 编码的图片数据）
    event: fields.ForeignKeyRelation[Event] = fields.ForeignKeyField(
        "models.Event",
        related_name="teams",
        on_delete=fields.CASCADE,
        index=True,
    )
    scores = fields.JSONField(default=dict)  # 分数存储，格式：{"round1": 100, "round2": 200}
    created_by: fields.ForeignKeyNullableRelation[User] = fields.ForeignKeyField(
        "models.User",
        related_name="created_teams",
        on_delete=fields.SET_NULL,
        null=True,
    )
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    members: fields.ManyToManyRelation[User] = fields.ManyToManyField(
        "models.User",
        related_name="teams",
        through="team_members"
    )

    class Meta(Model.Meta):
        table = "teams"


# ========== Maimai 乐曲数据 ==========


class MaiSong(Model):
    """Maimai 乐曲主表：存储乐曲基础信息"""

    id = fields.IntField(pk=True)  # 乐曲 ID
    title = fields.CharField(max_length=256, index=True)  # 乐曲标题
    artist = fields.CharField(max_length=256, null=True)  # 艺术家
    category = fields.CharField(max_length=64, null=True, index=True)  # 分类（dxrating）
    bpm = fields.IntField(null=True)  # BPM
    version = fields.CharField(max_length=32, null=True, index=True)  # 版本号
    rights = fields.TextField(null=True)  # 版权信息（LXNS）
    mai_map = fields.CharField(max_length=256, null=True, index=True)  # 地图名称（从Map XML或LXNS）
    
    # dxrating 独有字段
    release_date = fields.CharField(max_length=32, null=True)  # 发布日期
    is_new = fields.BooleanField(default=False)  # 是否新曲
    is_locked = fields.BooleanField(default=False)  # 是否锁定
    comment = fields.TextField(null=True)  # 备注信息
    
    # 难度数据（JSON 存储分组后的 difficulties 结构：{type: [sheets]})
    difficulties = fields.JSONField(default=dict)
    
    # 收藏信息（奖杯、称号等）
    # 格式: [{"type": "trophy", "id": 5102, "name": "39", "color": "Gold", "genre": "..."}]
    collections = fields.JSONField(default=list)

    # 元数据
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta(Model.Meta):
        table = "mai_songs"


class MaiMap(Model):
    """Maimai 地图数据表：存储从Map.xml解析的地图信息"""
    
    id = fields.IntField(pk=True)  # 地图ID（map_id）
    data_name = fields.CharField(max_length=128)  # 数据名称
    map_name = fields.CharField(max_length=256, index=True)  # 地图名称
    is_collabo = fields.BooleanField(default=False)  # 是否联动
    is_infinity = fields.BooleanField(default=False)  # 是否无限
    island_id = fields.IntField(null=True)  # 岛屿ID
    island_name = fields.CharField(max_length=256, null=True)  # 岛屿名称
    color_id = fields.IntField(null=True)  # 颜色ID
    color_name = fields.CharField(max_length=256, null=True)  # 颜色名称
    bonus_music_id = fields.IntField(null=True, index=True)  # 奖励音乐ID
    bonus_music_name = fields.CharField(max_length=256, null=True)  # 奖励音乐名称
    bonus_music_magnification = fields.IntField(null=True)  # 奖励音乐倍率
    open_event_id = fields.IntField(null=True)  # 开放活动ID
    open_event_name = fields.CharField(max_length=256, null=True)  # 开放活动名称
    net_open_name_id = fields.IntField(null=True)  # 网络开放名称ID
    net_open_name = fields.CharField(max_length=256, null=True)  # 网络开放名称
    
    # 奖励列表（JSON存储）
    treasures = fields.JSONField(default=list)
    
    # 元数据
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)
    
    class Meta(Model.Meta):
        table = "mai_maps"


class MaiMapTreasure(Model):
    """Maimai 地图奖励数据表：存储从MapTreasure.xml解析的奖励信息"""
    
    id = fields.IntField(pk=True)  # 奖励ID（item_id）
    data_name = fields.CharField(max_length=128)  # 数据名称
    treasure_name = fields.CharField(max_length=256, index=True)  # 奖励名称
    treasure_type = fields.CharField(max_length=64, index=True)  # 奖励类型
    character_id = fields.IntField(null=True)  # 角色ID
    character_name = fields.CharField(max_length=256, null=True)  # 角色名称
    music_id = fields.IntField(null=True, index=True)  # 音乐ID
    music_name = fields.CharField(max_length=256, null=True)  # 音乐名称
    numeric = fields.IntField(null=True)  # 数值
    name_plate_id = fields.IntField(null=True)  # 姓名牌ID
    name_plate_name = fields.CharField(max_length=256, null=True)  # 姓名牌名称
    frame_id = fields.IntField(null=True)  # 框架ID
    frame_name = fields.CharField(max_length=256, null=True)  # 框架名称
    title_id = fields.IntField(null=True)  # 称号ID
    title_name = fields.CharField(max_length=256, null=True)  # 称号名称
    icon_id = fields.IntField(null=True)  # 图标ID
    icon_name = fields.CharField(max_length=256, null=True)  # 图标名称
    challenge_id = fields.IntField(null=True)  # 挑战ID
    challenge_name = fields.CharField(max_length=256, null=True)  # 挑战名称
    gate_id = fields.IntField(null=True)  # 门ID
    gate_name = fields.CharField(max_length=256, null=True)  # 门名称
    key_id = fields.IntField(null=True)  # 钥匙ID
    key_name = fields.CharField(max_length=256, null=True)  # 钥匙名称
    
    # 元数据
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)
    
    class Meta(Model.Meta):
        table = "mai_map_treasures"


class MaiSongAlias(Model):
    """Maimai 乐曲别名表：一首乐曲可以有多个别名
    
    别名来源及优先级（priority值越小优先级越高）：
    1. 官方标题（来自dxrating/LXNS）
    2. dxrating API别名（通过songId直接匹配）
    3. LXNS社区别名（通过数字ID匹配）
    4. 柚子查社区别名（通过数字ID匹配）
    """

    id = fields.IntField(pk=True)
    song: fields.ForeignKeyRelation[MaiSong] = fields.ForeignKeyField(
        "models.MaiSong",
        related_name="aliases",
        on_delete=fields.CASCADE,
        index=True,
    )
    alias = fields.CharField(max_length=256, index=True)  # 别名文本
    # 用于排序/优先级：数字越小优先级越高（列表顺序决定）
    priority = fields.IntField(default=0)

    class Meta(Model.Meta):
        table = "mai_song_aliases"
        unique_together = (("song_id", "alias"),)


# ========== Chunithm 乐曲数据 ==========


class ChuniSong(Model):
    """Chunithm 乐曲主表：存储乐曲基础信息"""

    id = fields.IntField(pk=True)  # 乐曲 ID（来自 LXNS）
    title = fields.CharField(max_length=256, index=True)  # 乐曲标题
    artist = fields.CharField(max_length=256, null=True)  # 艺术家
    genre = fields.CharField(max_length=64, null=True, index=True)  # 曲风分类
    bpm = fields.IntField(null=True)  # BPM
    version = fields.IntField(null=True, index=True)  # 版本号
    rights = fields.TextField(null=True)  # 版权信息

    # 难度数据（JSON 存储完整的 difficulties 结构）
    difficulties = fields.JSONField(default=dict)

    # 元数据
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta(Model.Meta):
        table = "chuni_songs"


class ChuniSongAlias(Model):
    """Chunithm 乐曲别名表：一首乐曲可以有多个别名"""

    id = fields.IntField(pk=True)
    song: fields.ForeignKeyRelation[ChuniSong] = fields.ForeignKeyField(
        "models.ChuniSong",
        related_name="aliases",
        on_delete=fields.CASCADE,
        index=True,
    )
    alias = fields.CharField(max_length=256, index=True)  # 别名文本
    priority = fields.IntField(default=0)

    class Meta(Model.Meta):
        table = "chuni_song_aliases"
        unique_together = (("song_id", "alias"),)
