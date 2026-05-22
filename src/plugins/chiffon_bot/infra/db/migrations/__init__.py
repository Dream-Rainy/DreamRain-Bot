"""数据库迁移模块

此包包含数据库结构迁移脚本和自动迁移功能。

使用方法：
    from src.plugins.chiffon_bot.infra.db.migrations import auto_migrate
    await auto_migrate()
"""

from .auto_migrate import auto_migrate, get_migration_status
from .version_manager import CURRENT_DB_VERSION

__all__ = ["auto_migrate", "get_migration_status", "CURRENT_DB_VERSION"]
