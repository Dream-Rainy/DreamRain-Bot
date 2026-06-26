from pydantic import BaseModel, field_validator
from typing import Any
from src.plugins.permission_admin.core import normalize_group_whitelist


class Config(BaseModel):
    """Plugin Config Here"""
    lxns_api_key: str = ""
    lxns_client_id: str = ""
    lxns_client_secret: str = ""

    # LXNS / OAuth
    # 默认使用官方站点；如需自建/镜像可覆盖
    lxns_base_url: str = "https://maimai.lxns.net"
    # CHUNITHM 静态资源根（曲绘 /jacket/{id}.png 等），见 LXNS API 文档「游戏资源」
    chunithm_assets_base_url: str = "https://assets2.lxns.net/chunithm"
    # OAuth 回调地址（需与 LXNS 后台配置一致）；留空则从 relay redirect_uri 自动推导
    lxns_oauth_redirect_uri: str = ""
    # OAuth 中继服务地址（SSE Relay），如 https://relay.example.com
    lxns_oauth_relay_url: str = ""
    # OAuth 中继服务共享令牌，Bot ↔ Relay 鉴权
    lxns_oauth_relay_token: str = ""
    # OAuth scope（按 LXNS 实际支持调整）
    lxns_oauth_scope: str = ""
    # OAuth state 的有效期（秒）
    lxns_oauth_state_ttl_seconds: int = 600

    # Database
    # db_engine: sqlite / mysql / postgres（可按需扩展）
    # db_credentials: 直接对应 tortoise 的 credentials 字典
    #
    # 示例（sqlite）:
    #   db_engine="sqlite"
    #   db_url="data/chiffon_bot/db.sqlite3"
    #
    # 示例（postgres）:
    #   db_engine="postgres"
    #   db_credentials={"host":"127.0.0.1","port":5432,"user":"u","password":"p","database":"db"}
    #
    # 示例（mysql）:
    #   db_engine="mysql"
    #   db_credentials={"host":"127.0.0.1","port":3306,"user":"u","password":"p","database":"db"}
    db_engine: str = "sqlite"
    db_credentials: dict[str, Any] = {}

    # sqlite 便捷项：当 engine=sqlite 且未显式提供 db_credentials 时使用
    db_url: str = "data/chiffon_bot/db.sqlite3"

    # Timezone
    # 时区设置，用于赛事时间的显示和解析
    # 默认使用 Asia/Shanghai，可设置为任何有效的时区名称（如 UTC、America/New_York 等）
    timezone: str = "Asia/Shanghai"
    
    # ingame_data 基础路径
    # 子目录按约定自动推导：{base_dir}/{domain_name}/{data_type}/
    # 例如: {base_dir}/maimai/map/, {base_dir}/maimai/music/, {base_dir}/chunithm/music/
    # 如果路径为空或不可访问，将跳过 ingame 数据的解析
    ingame_data_base_dir: str = ""
    # Reaction
    # 消息确认表情的 emoji_id（NapCat OneBot V11 扩展）
    ack_emoji_id: str = "128064"

    chiffon_bot_group_whitelist: list[int] = []
    """允许使用 chiffon_bot 指令的群聊白名单，留空表示不启用白名单"""

    @field_validator("chiffon_bot_group_whitelist", mode="before")
    @classmethod
    def _parse_group_whitelist(cls, value):
        return sorted(normalize_group_whitelist(value))
