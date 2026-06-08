from pydantic import BaseModel

from nonebot import get_plugin_config


class Config(BaseModel):
    arena_auth_key: str = ""
    """arena 查询 API 的认证密钥"""
    priconne_captcha_auto: bool = True
    """priconne 登录是否优先自动过验证码"""
    priconne_captcha_admin_group: int = 0
    """priconne 手动验证码私聊失败时转发的群聊，0 表示不转发"""
    priconne_captcha_timeout: int = 120
    """priconne 手动验证码等待秒数"""


config = get_plugin_config(Config)
