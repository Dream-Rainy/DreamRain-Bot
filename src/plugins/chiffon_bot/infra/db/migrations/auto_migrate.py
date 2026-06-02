"""数据库自动迁移管理器

此模块负责检测数据库版本并自动执行需要的迁移。
"""

from tortoise import Tortoise
from nonebot import logger
from typing import List, Tuple, Callable

from .version_manager import (
    CURRENT_DB_VERSION,
    get_db_version,
    set_db_version,
    create_version_table,
    get_db_type,
    check_column_exists,
)


# 迁移列表：(版本号, 描述, 迁移函数)
# 按版本号顺序排列
MIGRATIONS: List[Tuple[int, str, Callable]] = []


def register_migration(version: int, description: str):
    """注册迁移的装饰器
    
    Args:
        version: 迁移版本号
        description: 迁移描述
    """
    def decorator(func):
        MIGRATIONS.append((version, description, func))
        # 按版本号排序
        MIGRATIONS.sort(key=lambda x: x[0])
        return func
    return decorator


# 注册所有迁移
from . import migration_v1_add_map_support

@register_migration(1, "添加 Map 和 MapTreasure 支持")
async def migrate_v1(conn):
    await migration_v1_add_map_support.apply(conn)


@register_migration(2, "添加 maimai 乐曲封面路径字段")
async def migrate_v2(conn):
    db_type = get_db_type(conn)
    logger.info(f"执行 {db_type} 迁移到 v2...")
    if not await check_column_exists(conn, "mai_songs", "image_name"):
        logger.info("  -> 在 mai_songs 表中添加 image_name 字段...")
        await conn.execute_query("ALTER TABLE mai_songs ADD COLUMN image_name VARCHAR(512)")
        logger.info("    ✓ image_name 字段添加成功")
    else:
        logger.info("  -> image_name 字段已存在，跳过")


@register_migration(3, "添加 CHUNITHM 乐曲封面路径字段")
async def migrate_v3(conn):
    db_type = get_db_type(conn)
    logger.info(f"执行 {db_type} 迁移到 v3...")
    if not await check_column_exists(conn, "chuni_songs", "image_name"):
        logger.info("  -> 在 chuni_songs 表中添加 image_name 字段...")
        await conn.execute_query("ALTER TABLE chuni_songs ADD COLUMN image_name VARCHAR(512)")
        logger.info("    ✓ image_name 字段添加成功")
    else:
        logger.info("  -> image_name 字段已存在，跳过")


async def auto_migrate(silent: bool = False) -> bool:
    """自动执行数据库迁移
    
    Args:
        silent: 是否静默模式（不输出详细日志）
        
    Returns:
        是否执行了迁移
    """
    try:
        # 获取数据库连接
        conn = Tortoise.get_connection("default")
        db_type = get_db_type(conn)
        
        if not silent:
            logger.info("=" * 60)
            logger.info("数据库自动迁移检查")
            logger.info("=" * 60)
            logger.info(f"数据库类型: {db_type}")
        
        # 创建版本表（如果不存在）
        await create_version_table(conn, db_type)
        
        # 获取当前数据库版本
        current_version = await get_db_version(conn)
        
        if not silent:
            logger.info(f"当前数据库版本: v{current_version}")
            logger.info(f"目标数据库版本: v{CURRENT_DB_VERSION}")
        
        # 检查是否需要迁移
        if current_version >= CURRENT_DB_VERSION:
            if not silent:
                logger.info("✓ 数据库已是最新版本，无需迁移")
            return False
        
        # 执行需要的迁移
        if not silent:
            logger.info("")
            logger.info(f"需要执行 {CURRENT_DB_VERSION - current_version} 个迁移")
            logger.info("-" * 60)
        
        migrations_applied = 0
        
        for version, description, migrate_func in MIGRATIONS:
            if version > current_version:
                if not silent:
                    logger.info("")
                    logger.info(f"▶ 执行迁移 v{version}: {description}")
                
                try:
                    # 执行迁移
                    await migrate_func(conn)
                    
                    # 更新版本
                    await set_db_version(conn, version, description)
                    
                    migrations_applied += 1
                    
                    if not silent:
                        logger.info(f"  ✓ 迁移 v{version} 完成")
                        
                except Exception as e:
                    logger.error(f"  ✗ 迁移 v{version} 失败: {e}")
                    raise
        
        if not silent:
            logger.info("")
            logger.info("-" * 60)
            logger.info(f"✓ 所有迁移已完成！共执行 {migrations_applied} 个迁移")
            logger.info("=" * 60)
        
        return True
        
    except Exception as e:
        logger.error(f"自动迁移失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def get_migration_status() -> dict:
    """获取迁移状态信息
    
    Returns:
        包含版本信息和待执行迁移的字典
    """
    try:
        conn = Tortoise.get_connection("default")
        db_type = get_db_type(conn)
        
        # 创建版本表（如果不存在）
        await create_version_table(conn, db_type)
        
        current_version = await get_db_version(conn)
        
        # 获取待执行的迁移
        pending_migrations = []
        for version, description, _ in MIGRATIONS:
            if version > current_version:
                pending_migrations.append({
                    "version": version,
                    "description": description
                })
        
        return {
            "db_type": db_type,
            "current_version": current_version,
            "target_version": CURRENT_DB_VERSION,
            "is_up_to_date": current_version >= CURRENT_DB_VERSION,
            "pending_migrations": pending_migrations,
            "migrations_count": len(pending_migrations)
        }
    except Exception as e:
        logger.error(f"获取迁移状态失败: {e}")
        return {
            "error": str(e)
        }
