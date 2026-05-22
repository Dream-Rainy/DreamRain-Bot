from pydantic import BaseModel, Field, field_validator

from nonebot import get_plugin_config

from .core import normalize_group_whitelist


class Config(BaseModel):
    """permission_admin 插件配置。"""

    control_groups: list[int] = Field(
        default_factory=list,
        description="控制台群号列表；仅在这些群内可使用 perm glob 远程设置其它群的插件开关；留空则关闭该功能",
    )

    @field_validator("control_groups", mode="before")
    @classmethod
    def _parse_control_groups(cls, value: object) -> list[int]:
        return sorted(normalize_group_whitelist(value))


plugin_config = get_plugin_config(Config)
