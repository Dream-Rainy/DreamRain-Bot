"""数据库版本管理和自动迁移系统

此模块提供数据库版本跟踪和自动迁移功能。
"""

from tortoise import Tortoise
from nonebot import logger


# 数据库当前目标版本（每次添加新迁移时递增）
CURRENT_DB_VERSION = 3


async def get_db_version(conn) -> int:
    """获取当前数据库版本
    
    Returns:
        当前数据库版本号，如果版本表不存在返回 0
    """
    try:
        # 检查版本表是否存在
        engine_str = str(type(conn).__module__)
        
        if "sqlite" in engine_str:
            query = "SELECT name FROM sqlite_master WHERE type='table' AND name='db_version'"
            result = await conn.execute_query(query)
            if not result[1]:
                return 0
            # 获取版本
            result = await conn.execute_query("SELECT version FROM db_version ORDER BY id DESC LIMIT 1")
            return result[1][0][0] if result[1] else 0
            
        elif "asyncpg" in engine_str or "postgres" in engine_str:
            query = "SELECT tablename FROM pg_tables WHERE tablename = $1"
            result = await conn.execute_query(query, ["db_version"])
            if not result[1]:
                return 0
            # 获取版本
            result = await conn.execute_query("SELECT version FROM db_version ORDER BY id DESC LIMIT 1")
            return result[1][0][0] if result[1] else 0
            
        elif "mysql" in engine_str:
            query = "SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s"
            result = await conn.execute_query(query, ["db_version"])
            if not result[1]:
                return 0
            # 获取版本
            result = await conn.execute_query("SELECT version FROM db_version ORDER BY id DESC LIMIT 1")
            return result[1][0][0] if result[1] else 0
            
    except Exception as e:
        logger.debug(f"获取数据库版本时出错（可能是首次运行）: {e}")
        return 0
    
    return 0


async def create_version_table(conn, db_type: str):
    """创建版本表"""
    try:
        if db_type == "sqlite":
            await conn.execute_query("""
                CREATE TABLE IF NOT EXISTS db_version (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    version INTEGER NOT NULL,
                    applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    description TEXT
                )
            """)
        elif db_type == "postgres":
            await conn.execute_query("""
                CREATE TABLE IF NOT EXISTS db_version (
                    id SERIAL PRIMARY KEY,
                    version INTEGER NOT NULL,
                    applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    description TEXT
                )
            """)
        elif db_type == "mysql":
            await conn.execute_query("""
                CREATE TABLE IF NOT EXISTS db_version (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    version INT NOT NULL,
                    applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    description TEXT
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)
        logger.debug("版本表创建成功")
    except Exception as e:
        logger.error(f"创建版本表失败: {e}")
        raise


async def set_db_version(conn, version: int, description: str = ""):
    """设置数据库版本
    
    Args:
        conn: 数据库连接
        version: 版本号
        description: 版本描述
    """
    try:
        engine_str = str(type(conn).__module__)
        
        if "sqlite" in engine_str:
            await conn.execute_query(
                "INSERT INTO db_version (version, description) VALUES (?, ?)",
                [version, description]
            )
        elif "asyncpg" in engine_str or "postgres" in engine_str:
            await conn.execute_query(
                "INSERT INTO db_version (version, description) VALUES ($1, $2)",
                [version, description]
            )
        elif "mysql" in engine_str:
            await conn.execute_query(
                "INSERT INTO db_version (version, description) VALUES (%s, %s)",
                [version, description]
            )
        
        logger.info(f"数据库版本已更新至 v{version}")
    except Exception as e:
        logger.error(f"设置数据库版本失败: {e}")
        raise


async def check_column_exists(conn, table_name: str, column_name: str) -> bool:
    """检查列是否存在"""
    try:
        engine_str = str(type(conn).__module__)
        
        if "sqlite" in engine_str:
            result = await conn.execute_query(f"PRAGMA table_info({table_name})")
            columns = [row[1] for row in result[1]]
            return column_name in columns
        elif "asyncpg" in engine_str or "postgres" in engine_str:
            query = """
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = $1 AND column_name = $2
            """
            result = await conn.execute_query(query, [table_name, column_name])
            return len(result[1]) > 0
        elif "mysql" in engine_str:
            query = """
                SELECT COLUMN_NAME 
                FROM INFORMATION_SCHEMA.COLUMNS 
                WHERE TABLE_SCHEMA = DATABASE() 
                AND TABLE_NAME = %s AND COLUMN_NAME = %s
            """
            result = await conn.execute_query(query, [table_name, column_name])
            return len(result[1]) > 0
    except Exception as e:
        logger.error(f"检查列是否存在时出错: {e}")
        return False
    return False


async def check_table_exists(conn, table_name: str) -> bool:
    """检查表是否存在"""
    try:
        engine_str = str(type(conn).__module__)
        
        if "sqlite" in engine_str:
            query = "SELECT name FROM sqlite_master WHERE type='table' AND name=?"
            result = await conn.execute_query(query, [table_name])
            return len(result[1]) > 0
        elif "asyncpg" in engine_str or "postgres" in engine_str:
            query = "SELECT tablename FROM pg_tables WHERE tablename = $1"
            result = await conn.execute_query(query, [table_name])
            return len(result[1]) > 0
        elif "mysql" in engine_str:
            query = "SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s"
            result = await conn.execute_query(query, [table_name])
            return len(result[1]) > 0
    except Exception as e:
        logger.error(f"检查表是否存在时出错: {e}")
        return False
    return False


def get_db_type(conn) -> str:
    """获取数据库类型"""
    engine_str = str(type(conn).__module__)
    if "sqlite" in engine_str:
        return "sqlite"
    elif "asyncpg" in engine_str or "postgres" in engine_str:
        return "postgres"
    elif "mysql" in engine_str:
        return "mysql"
    return "unknown"
