"""数据库迁移脚本：添加 Map 相关表和字段

此脚本用于将现有数据库迁移到支持 Map XML 解析功能的新结构。

迁移内容：
1. 在 mai_songs 表中添加 mai_map 字段
2. 创建 mai_maps 表
3. 创建 mai_map_treasures 表

使用方法：
    python -m src.plugins.chiffon_bot.infra.db.migrations.add_map_support

注意事项：
- 此脚本会自动检测数据库类型（sqlite/postgres/mysql）
- 迁移操作是幂等的，可以安全地重复执行
- 建议在执行前备份数据库
"""

import asyncio
import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from tortoise import Tortoise
from nonebot import logger


async def check_column_exists(conn, table_name: str, column_name: str, db_type: str) -> bool:
    """检查列是否存在"""
    try:
        if db_type == "sqlite":
            result = await conn.execute_query(f"PRAGMA table_info({table_name})")
            columns = [row[1] for row in result[1]]
            return column_name in columns
        elif db_type == "postgres":
            query = """
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = $1 AND column_name = $2
            """
            result = await conn.execute_query(query, [table_name, column_name])
            return len(result[1]) > 0
        elif db_type == "mysql":
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


async def check_table_exists(conn, table_name: str, db_type: str) -> bool:
    """检查表是否存在"""
    try:
        if db_type == "sqlite":
            query = "SELECT name FROM sqlite_master WHERE type='table' AND name=?"
            result = await conn.execute_query(query, [table_name])
            return len(result[1]) > 0
        elif db_type == "postgres":
            query = "SELECT tablename FROM pg_tables WHERE tablename = $1"
            result = await conn.execute_query(query, [table_name])
            return len(result[1]) > 0
        elif db_type == "mysql":
            query = "SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s"
            result = await conn.execute_query(query, [table_name])
            return len(result[1]) > 0
    except Exception as e:
        logger.error(f"检查表是否存在时出错: {e}")
        return False
    return False


async def migrate_sqlite(conn):
    """SQLite 数据库迁移"""
    logger.info("开始 SQLite 数据库迁移...")
    
    # 1. 检查并添加 mai_map 字段到 mai_songs 表
    if not await check_column_exists(conn, "mai_songs", "mai_map", "sqlite"):
        logger.info("在 mai_songs 表中添加 mai_map 字段...")
        await conn.execute_query("ALTER TABLE mai_songs ADD COLUMN mai_map VARCHAR(256)")
        await conn.execute_query("CREATE INDEX IF NOT EXISTS idx_mai_songs_mai_map ON mai_songs (mai_map)")
        logger.info("✓ mai_map 字段添加成功")
    else:
        logger.info("mai_map 字段已存在，跳过")
    
    # 2. 创建 mai_maps 表
    if not await check_table_exists(conn, "mai_maps", "sqlite"):
        logger.info("创建 mai_maps 表...")
        await conn.execute_query("""
            CREATE TABLE mai_maps (
                id INTEGER PRIMARY KEY,
                data_name VARCHAR(128) NOT NULL,
                map_name VARCHAR(256) NOT NULL,
                is_collabo INTEGER NOT NULL DEFAULT 0,
                is_infinity INTEGER NOT NULL DEFAULT 0,
                island_id INTEGER,
                island_name VARCHAR(256),
                color_id INTEGER,
                color_name VARCHAR(256),
                bonus_music_id INTEGER,
                bonus_music_name VARCHAR(256),
                bonus_music_magnification INTEGER,
                open_event_id INTEGER,
                open_event_name VARCHAR(256),
                net_open_name_id INTEGER,
                net_open_name VARCHAR(256),
                treasures TEXT NOT NULL DEFAULT '[]',
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await conn.execute_query("CREATE INDEX idx_mai_maps_map_name ON mai_maps (map_name)")
        await conn.execute_query("CREATE INDEX idx_mai_maps_bonus_music_id ON mai_maps (bonus_music_id)")
        logger.info("✓ mai_maps 表创建成功")
    else:
        logger.info("mai_maps 表已存在，跳过")
    
    # 3. 创建 mai_map_treasures 表
    if not await check_table_exists(conn, "mai_map_treasures", "sqlite"):
        logger.info("创建 mai_map_treasures 表...")
        await conn.execute_query("""
            CREATE TABLE mai_map_treasures (
                id INTEGER PRIMARY KEY,
                data_name VARCHAR(128) NOT NULL,
                treasure_name VARCHAR(256) NOT NULL,
                treasure_type VARCHAR(64) NOT NULL,
                character_id INTEGER,
                character_name VARCHAR(256),
                music_id INTEGER,
                music_name VARCHAR(256),
                numeric INTEGER,
                name_plate_id INTEGER,
                name_plate_name VARCHAR(256),
                frame_id INTEGER,
                frame_name VARCHAR(256),
                title_id INTEGER,
                title_name VARCHAR(256),
                icon_id INTEGER,
                icon_name VARCHAR(256),
                challenge_id INTEGER,
                challenge_name VARCHAR(256),
                gate_id INTEGER,
                gate_name VARCHAR(256),
                key_id INTEGER,
                key_name VARCHAR(256),
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await conn.execute_query("CREATE INDEX idx_mai_map_treasures_treasure_name ON mai_map_treasures (treasure_name)")
        await conn.execute_query("CREATE INDEX idx_mai_map_treasures_treasure_type ON mai_map_treasures (treasure_type)")
        await conn.execute_query("CREATE INDEX idx_mai_map_treasures_music_id ON mai_map_treasures (music_id)")
        logger.info("✓ mai_map_treasures 表创建成功")
    else:
        logger.info("mai_map_treasures 表已存在，跳过")


async def migrate_postgres(conn):
    """PostgreSQL 数据库迁移"""
    logger.info("开始 PostgreSQL 数据库迁移...")
    
    # 1. 检查并添加 mai_map 字段到 mai_songs 表
    if not await check_column_exists(conn, "mai_songs", "mai_map", "postgres"):
        logger.info("在 mai_songs 表中添加 mai_map 字段...")
        await conn.execute_query("ALTER TABLE mai_songs ADD COLUMN mai_map VARCHAR(256)")
        await conn.execute_query("CREATE INDEX IF NOT EXISTS idx_mai_songs_mai_map ON mai_songs (mai_map)")
        logger.info("✓ mai_map 字段添加成功")
    else:
        logger.info("mai_map 字段已存在，跳过")
    
    # 2. 创建 mai_maps 表
    if not await check_table_exists(conn, "mai_maps", "postgres"):
        logger.info("创建 mai_maps 表...")
        await conn.execute_query("""
            CREATE TABLE mai_maps (
                id INTEGER PRIMARY KEY,
                data_name VARCHAR(128) NOT NULL,
                map_name VARCHAR(256) NOT NULL,
                is_collabo BOOLEAN NOT NULL DEFAULT FALSE,
                is_infinity BOOLEAN NOT NULL DEFAULT FALSE,
                island_id INTEGER,
                island_name VARCHAR(256),
                color_id INTEGER,
                color_name VARCHAR(256),
                bonus_music_id INTEGER,
                bonus_music_name VARCHAR(256),
                bonus_music_magnification INTEGER,
                open_event_id INTEGER,
                open_event_name VARCHAR(256),
                net_open_name_id INTEGER,
                net_open_name VARCHAR(256),
                treasures JSONB NOT NULL DEFAULT '[]'::jsonb,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await conn.execute_query("CREATE INDEX idx_mai_maps_map_name ON mai_maps (map_name)")
        await conn.execute_query("CREATE INDEX idx_mai_maps_bonus_music_id ON mai_maps (bonus_music_id)")
        logger.info("✓ mai_maps 表创建成功")
    else:
        logger.info("mai_maps 表已存在，跳过")
    
    # 3. 创建 mai_map_treasures 表
    if not await check_table_exists(conn, "mai_map_treasures", "postgres"):
        logger.info("创建 mai_map_treasures 表...")
        await conn.execute_query("""
            CREATE TABLE mai_map_treasures (
                id INTEGER PRIMARY KEY,
                data_name VARCHAR(128) NOT NULL,
                treasure_name VARCHAR(256) NOT NULL,
                treasure_type VARCHAR(64) NOT NULL,
                character_id INTEGER,
                character_name VARCHAR(256),
                music_id INTEGER,
                music_name VARCHAR(256),
                numeric INTEGER,
                name_plate_id INTEGER,
                name_plate_name VARCHAR(256),
                frame_id INTEGER,
                frame_name VARCHAR(256),
                title_id INTEGER,
                title_name VARCHAR(256),
                icon_id INTEGER,
                icon_name VARCHAR(256),
                challenge_id INTEGER,
                challenge_name VARCHAR(256),
                gate_id INTEGER,
                gate_name VARCHAR(256),
                key_id INTEGER,
                key_name VARCHAR(256),
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await conn.execute_query("CREATE INDEX idx_mai_map_treasures_treasure_name ON mai_map_treasures (treasure_name)")
        await conn.execute_query("CREATE INDEX idx_mai_map_treasures_treasure_type ON mai_map_treasures (treasure_type)")
        await conn.execute_query("CREATE INDEX idx_mai_map_treasures_music_id ON mai_map_treasures (music_id)")
        logger.info("✓ mai_map_treasures 表创建成功")
    else:
        logger.info("mai_map_treasures 表已存在，跳过")


async def migrate_mysql(conn):
    """MySQL 数据库迁移"""
    logger.info("开始 MySQL 数据库迁移...")
    
    # 1. 检查并添加 mai_map 字段到 mai_songs 表
    if not await check_column_exists(conn, "mai_songs", "mai_map", "mysql"):
        logger.info("在 mai_songs 表中添加 mai_map 字段...")
        await conn.execute_query("ALTER TABLE mai_songs ADD COLUMN mai_map VARCHAR(256)")
        await conn.execute_query("CREATE INDEX idx_mai_songs_mai_map ON mai_songs (mai_map)")
        logger.info("✓ mai_map 字段添加成功")
    else:
        logger.info("mai_map 字段已存在，跳过")
    
    # 2. 创建 mai_maps 表
    if not await check_table_exists(conn, "mai_maps", "mysql"):
        logger.info("创建 mai_maps 表...")
        await conn.execute_query("""
            CREATE TABLE mai_maps (
                id INTEGER PRIMARY KEY,
                data_name VARCHAR(128) NOT NULL,
                map_name VARCHAR(256) NOT NULL,
                is_collabo TINYINT(1) NOT NULL DEFAULT 0,
                is_infinity TINYINT(1) NOT NULL DEFAULT 0,
                island_id INTEGER,
                island_name VARCHAR(256),
                color_id INTEGER,
                color_name VARCHAR(256),
                bonus_music_id INTEGER,
                bonus_music_name VARCHAR(256),
                bonus_music_magnification INTEGER,
                open_event_id INTEGER,
                open_event_name VARCHAR(256),
                net_open_name_id INTEGER,
                net_open_name VARCHAR(256),
                treasures JSON NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                INDEX idx_mai_maps_map_name (map_name),
                INDEX idx_mai_maps_bonus_music_id (bonus_music_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
        logger.info("✓ mai_maps 表创建成功")
    else:
        logger.info("mai_maps 表已存在，跳过")
    
    # 3. 创建 mai_map_treasures 表
    if not await check_table_exists(conn, "mai_map_treasures", "mysql"):
        logger.info("创建 mai_map_treasures 表...")
        await conn.execute_query("""
            CREATE TABLE mai_map_treasures (
                id INTEGER PRIMARY KEY,
                data_name VARCHAR(128) NOT NULL,
                treasure_name VARCHAR(256) NOT NULL,
                treasure_type VARCHAR(64) NOT NULL,
                character_id INTEGER,
                character_name VARCHAR(256),
                music_id INTEGER,
                music_name VARCHAR(256),
                numeric INTEGER,
                name_plate_id INTEGER,
                name_plate_name VARCHAR(256),
                frame_id INTEGER,
                frame_name VARCHAR(256),
                title_id INTEGER,
                title_name VARCHAR(256),
                icon_id INTEGER,
                icon_name VARCHAR(256),
                challenge_id INTEGER,
                challenge_name VARCHAR(256),
                gate_id INTEGER,
                gate_name VARCHAR(256),
                key_id INTEGER,
                key_name VARCHAR(256),
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                INDEX idx_mai_map_treasures_treasure_name (treasure_name),
                INDEX idx_mai_map_treasures_treasure_type (treasure_type),
                INDEX idx_mai_map_treasures_music_id (music_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
        logger.info("✓ mai_map_treasures 表创建成功")
    else:
        logger.info("mai_map_treasures 表已存在，跳过")


async def run_migration():
    """执行数据库迁移"""
    connect = None
    try:
        # 初始化数据库连接
        from src.plugins.chiffon_bot.infra.db import connect as db_connect
        connect = db_connect
        
        logger.info("=" * 60)
        logger.info("数据库迁移：添加 Map 相关表和字段")
        logger.info("=" * 60)
        
        # 初始化 Tortoise ORM
        await connect.init()
        
        # 获取数据库连接
        conn = Tortoise.get_connection("default")
        
        # 确定数据库类型 - 通过查看 engine 字符串
        db_type = None
        engine_str = str(type(conn).__module__)
        
        if "sqlite" in engine_str:
            db_type = "sqlite"
        elif "asyncpg" in engine_str or "postgres" in engine_str:
            db_type = "postgres"
        elif "mysql" in engine_str:
            db_type = "mysql"
        else:
            logger.error(f"不支持的数据库类型: {engine_str}")
            return False
        
        logger.info(f"检测到数据库类型: {db_type}")
        logger.info("")
        
        # 创建备份提示
        logger.warning("⚠️  建议在执行迁移前备份数据库！")
        logger.info("")
        
        # 执行对应的迁移
        if db_type == "sqlite":
            await migrate_sqlite(conn)
        elif db_type == "postgres":
            await migrate_postgres(conn)
        elif db_type == "mysql":
            await migrate_mysql(conn)
        
        logger.info("")
        logger.info("=" * 60)
        logger.info("✓ 数据库迁移完成！")
        logger.info("=" * 60)
        logger.info("")
        logger.info("迁移内容：")
        logger.info("  1. 在 mai_songs 表中添加 mai_map 字段")
        logger.info("  2. 创建 mai_maps 表")
        logger.info("  3. 创建 mai_map_treasures 表")
        logger.info("")
        logger.info("下一步：")
        logger.info("  1. 在配置文件中设置 map_xml_base_dir 和 map_treasure_xml_base_dir")
        logger.info("  2. 重启机器人以加载新的数据结构")
        logger.info("  3. 执行数据刷新以解析 Map XML 数据")
        logger.info("")
        
        return True
        
    except Exception as e:
        logger.error(f"数据库迁移失败: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        if connect:
            await connect.close()


if __name__ == "__main__":
    # 设置日志
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    
    # 运行迁移
    success = asyncio.run(run_migration())
    sys.exit(0 if success else 1)
