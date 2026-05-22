from os.path import join

from pydantic import BaseModel, field_validator

from nonebot import get_plugin_config
from src.plugins.permission_admin.core import normalize_group_whitelist


class AccountInfo(BaseModel):
    """账号信息"""
    account: str 
    """登录账号"""
    password: str 
    """账号密码"""


class Config(BaseModel):
    """插件配置"""
    apscheduler_log_level: int = 30
    data_path: str = join("data", "pcrjjc") 
    """数据存储目录"""
    superusers: list[str]  
    """超级用户列表，建议只填一个，填多个可能导致后续用户指令失效"""
    pcrjjc_group: int = 0  
    """当私聊不可用时，使用指定群聊推送要私聊的消息"""
    otto: bool = True  
    """是否自动过验证码，因自动过码失效，改为手动过码"""
    max_pri: int = 0  
    """最大私聊人数"""
    max_pcrid: int = 8  
    """每个QQ号绑定的最多数量"""
    max_history: int = 50  
    """每个QQ号保存的最多击剑记录"""
    notice_cd_min: int = 10  
    """上线推送频率"""
    refresh_second: int = 3
    """刷新频率，可按自身服务器性能输入其他数值，可支持整数、小数"""
    pcrjjc_accounts: list[AccountInfo] = []
    """登录账号"""
    pcrjjc_group_whitelist: list[int] = []
    """允许使用 pcrjjc 指令的群聊白名单，留空表示不启用白名单"""
    font_download_url: str = "https://github.com/reine-ishyanami/nonebot-plugin-pcrjjc/releases/download/font/SourceHanSansCN-Medium.otf"
    """默认字体下载地址"""

    @field_validator("pcrjjc_group_whitelist", mode="before")
    @classmethod
    def _parse_group_whitelist(cls, value):
        return sorted(normalize_group_whitelist(value))

config = get_plugin_config(Config)