from pydantic import BaseModel

from nonebot import get_plugin_config


class Config(BaseModel):
    arena_auth_key: str = ""
    """arena 查询 API 的认证密钥"""


config = get_plugin_config(Config)
