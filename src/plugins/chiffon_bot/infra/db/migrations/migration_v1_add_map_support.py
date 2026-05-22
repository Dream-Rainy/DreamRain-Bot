"""数据库迁移 v1: 添加 Map 支持

版本: 1
描述: 添加 Map 和 MapTreasure 相关表结构
日期: 2026-01-27

变更内容:
- 在 mai_songs 表添加 mai_map 字段
- 创建 mai_maps 表
- 创建 mai_map_treasures 表
"""

from nonebot import logger
from .version_manager import check_column_exists, check_table_exists, get_db_type


async def upgrade_sqlite(conn):
    """SQLite 升级到 v1"""
    logger.info("执行 SQLite 迁移到 v1...")
    
    # 1. 添加 mai_map 字段
    if not await check_column_exists(conn, "mai_songs", "mai_map"):
        logger.info("  → 在 mai_songs 表中添加 mai_map 字段...")
        await conn.execute_query("ALTER TABLE mai_songs ADD COLUMN mai_map VARCHAR(256)")
        await conn.execute_query("CREATE INDEX IF NOT EXISTS idx_mai_songs_mai_map ON mai_songs (mai_map)")
        logger.info("    ✓ mai_map 字段添加成功")
    else:
        logger.info("  → mai_map 字段已存在，跳过")
    
    # 2. 创建 mai_maps 表
    if not await check_table_exists(conn, "mai_maps"):
        logger.info("  → 创建 mai_maps 表...")
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
        logger.info("    ✓ mai_maps 表创建成功")
    else:
        logger.info("  → mai_maps 表已存在，跳过")
    
    # 3. 创建 mai_map_treasures 表
    if not await check_table_exists(conn, "mai_map_treasures"):
        logger.info("  → 创建 mai_map_treasures 表...")
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
        logger.info("    ✓ mai_map_treasures 表创建成功")
    else:
        logger.info("  → mai_map_treasures 表已存在，跳过")


async def upgrade_postgres(conn):
    """PostgreSQL 升级到 v1"""
    logger.info("执行 PostgreSQL 迁移到 v1...")
    
    # 1. 添加 mai_map 字段
    if not await check_column_exists(conn, "mai_songs", "mai_map"):
        logger.info("  → 在 mai_songs 表中添加 mai_map 字段...")
        await conn.execute_query("ALTER TABLE mai_songs ADD COLUMN mai_map VARCHAR(256)")
        await conn.execute_query("CREATE INDEX IF NOT EXISTS idx_mai_songs_mai_map ON mai_songs (mai_map)")
        logger.info("    ✓ mai_map 字段添加成功")
    else:
        logger.info("  → mai_map 字段已存在，跳过")
    
    # 2. 创建 mai_maps 表
    if not await check_table_exists(conn, "mai_maps"):
        logger.info("  → 创建 mai_maps 表...")
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
                created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await conn.execute_query("CREATE INDEX idx_mai_maps_map_name ON mai_maps (map_name)")
        await conn.execute_query("CREATE INDEX idx_mai_maps_bonus_music_id ON mai_maps (bonus_music_id)")
        logger.info("    ✓ mai_maps 表创建成功")
    else:
        logger.info("  → mai_maps 表已存在，跳过")
    
    # 3. 创建 mai_map_treasures 表
    if not await check_table_exists(conn, "mai_map_treasures"):
        logger.info("  → 创建 mai_map_treasures 表...")
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
                created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await conn.execute_query("CREATE INDEX idx_mai_map_treasures_treasure_name ON mai_map_treasures (treasure_name)")
        await conn.execute_query("CREATE INDEX idx_mai_map_treasures_treasure_type ON mai_map_treasures (treasure_type)")
        await conn.execute_query("CREATE INDEX idx_mai_map_treasures_music_id ON mai_map_treasures (music_id)")
        logger.info("    ✓ mai_map_treasures 表创建成功")
    else:
        logger.info("  → mai_map_treasures 表已存在，跳过")


async def upgrade_mysql(conn):
    """MySQL 升级到 v1"""
    logger.info("执行 MySQL 迁移到 v1...")
    
    # 1. 添加 mai_map 字段
    if not await check_column_exists(conn, "mai_songs", "mai_map"):
        logger.info("  → 在 mai_songs 表中添加 mai_map 字段...")
        await conn.execute_query("ALTER TABLE mai_songs ADD COLUMN mai_map VARCHAR(256)")
        await conn.execute_query("CREATE INDEX idx_mai_songs_mai_map ON mai_songs (mai_map)")
        logger.info("    ✓ mai_map 字段添加成功")
    else:
        logger.info("  → mai_map 字段已存在，跳过")
    
    # 2. 创建 mai_maps 表
    if not await check_table_exists(conn, "mai_maps"):
        logger.info("  → 创建 mai_maps 表...")
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
        logger.info("    ✓ mai_maps 表创建成功")
    else:
        logger.info("  → mai_maps 表已存在，跳过")
    
    # 3. 创建 mai_map_treasures 表
    if not await check_table_exists(conn, "mai_map_treasures"):
        logger.info("  → 创建 mai_map_treasures 表...")
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
        logger.info("    ✓ mai_map_treasures 表创建成功")
    else:
        logger.info("  → mai_map_treasures 表已存在，跳过")


async def apply(conn):
    """应用此迁移"""
    db_type = get_db_type(conn)
    
    if db_type == "sqlite":
        await upgrade_sqlite(conn)
    elif db_type == "postgres":
        await upgrade_postgres(conn)
    elif db_type == "mysql":
        await upgrade_mysql(conn)
    else:
        raise ValueError(f"不支持的数据库类型: {db_type}")
