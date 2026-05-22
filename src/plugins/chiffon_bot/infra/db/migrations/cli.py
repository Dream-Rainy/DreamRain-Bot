"""数据库迁移命令行工具

提供手动执行和查看迁移状态的命令。

使用方法：
    # 查看迁移状态
    python -m src.plugins.chiffon_bot.infra.db.migrations.cli status
    
    # 执行迁移
    python -m src.plugins.chiffon_bot.infra.db.migrations.cli migrate
    
    # 查看迁移历史
    python -m src.plugins.chiffon_bot.infra.db.migrations.cli history
"""

import asyncio
import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))


async def show_status():
    """显示迁移状态"""
    from tortoise import Tortoise
    from src.plugins.chiffon_bot.infra.db import connect
    from .auto_migrate import get_migration_status
    
    try:
        print("=" * 70)
        print(" 数据库迁移状态 ".center(70, "="))
        print("=" * 70)
        print()
        
        # 初始化数据库连接
        await connect.init()
        
        # 获取状态
        status = await get_migration_status()
        
        if "error" in status:
            print(f"❌ 获取状态失败: {status['error']}")
            return
        
        print(f"📊 数据库类型: {status['db_type']}")
        print(f"📌 当前版本:   v{status['current_version']}")
        print(f"🎯 目标版本:   v{status['target_version']}")
        print()
        
        if status['is_up_to_date']:
            print("✅ 数据库已是最新版本！")
        else:
            print(f"⚠️  数据库需要更新，有 {status['migrations_count']} 个待执行的迁移：")
            print()
            for migration in status['pending_migrations']:
                print(f"  • v{migration['version']}: {migration['description']}")
        
        print()
        print("=" * 70)
        
    except Exception as e:
        print(f"❌ 错误: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await connect.close()


async def run_migrate():
    """执行迁移"""
    from src.plugins.chiffon_bot.infra.db import connect
    from .auto_migrate import auto_migrate
    
    try:
        print("=" * 70)
        print(" 数据库迁移执行 ".center(70, "="))
        print("=" * 70)
        print()
        
        # 初始化数据库连接
        await connect.init()
        
        # 执行迁移
        result = await auto_migrate(silent=False)
        
        if result:
            print()
            print("✅ 迁移成功完成！")
        else:
            print()
            print("ℹ️  无需迁移或迁移已完成")
        
    except Exception as e:
        print()
        print(f"❌ 迁移失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        await connect.close()


async def show_history():
    """显示迁移历史"""
    from tortoise import Tortoise
    from src.plugins.chiffon_bot.infra.db import connect
    from .version_manager import get_db_type
    
    try:
        print("=" * 70)
        print(" 数据库迁移历史 ".center(70, "="))
        print("=" * 70)
        print()
        
        # 初始化数据库连接
        await connect.init()
        
        conn = Tortoise.get_connection("default")
        db_type = get_db_type(conn)
        
        result = None
        
        # 检查版本表是否存在
        if db_type == "sqlite":
            query = "SELECT name FROM sqlite_master WHERE type='table' AND name='db_version'"
            result = await conn.execute_query(query)
            if not result[1]:
                print("ℹ️  尚未执行过任何迁移")
                return
            
            # 获取历史记录
            query = "SELECT version, description, applied_at FROM db_version ORDER BY id"
            result = await conn.execute_query(query)
            
        elif "asyncpg" in str(type(conn).__module__) or "postgres" in str(type(conn).__module__):
            query = "SELECT tablename FROM pg_tables WHERE tablename = $1"
            result = await conn.execute_query(query, ["db_version"])
            if not result[1]:
                print("ℹ️  尚未执行过任何迁移")
                return
            
            query = "SELECT version, description, applied_at FROM db_version ORDER BY id"
            result = await conn.execute_query(query)
            
        elif "mysql" in str(type(conn).__module__):
            query = "SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s"
            result = await conn.execute_query(query, ["db_version"])
            if not result[1]:
                print("ℹ️  尚未执行过任何迁移")
                return
            
            query = "SELECT version, description, applied_at FROM db_version ORDER BY id"
            result = await conn.execute_query(query)
        
        if not result or not result[1]:
            print("ℹ️  尚未执行过任何迁移")
            return
        
        print(f"{'版本':<10} {'描述':<40} {'执行时间':<25}")
        print("-" * 70)
        
        for row in result[1]:
            version, description, applied_at = row
            print(f"v{version:<9} {description:<40} {str(applied_at):<25}")
        
        print()
        print("=" * 70)
        
    except Exception as e:
        print(f"❌ 错误: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await connect.close()


def main():
    """主函数"""
    if len(sys.argv) < 2:
        print("用法:")
        print("  python -m src.plugins.chiffon_bot.infra.db.migrations.cli <command>")
        print()
        print("命令:")
        print("  status   - 查看迁移状态")
        print("  migrate  - 执行迁移")
        print("  history  - 查看迁移历史")
        sys.exit(1)
    
    command = sys.argv[1].lower()
    
    if command == "status":
        asyncio.run(show_status())
    elif command == "migrate":
        asyncio.run(run_migrate())
    elif command == "history":
        asyncio.run(show_history())
    else:
        print(f"❌ 未知命令: {command}")
        print()
        print("可用命令: status, migrate, history")
        sys.exit(1)


if __name__ == "__main__":
    main()
