"""测试数据库迁移系统

此脚本用于测试自动迁移功能是否正常工作。
"""

import asyncio
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))


async def test_migration():
    """测试迁移功能"""
    from src.plugins.chiffon_bot.infra.db import connect
    from src.plugins.chiffon_bot.infra.db.migrations import auto_migrate, get_migration_status
    
    print("=" * 70)
    print(" 数据库迁移系统测试 ".center(70, "="))
    print("=" * 70)
    print()
    
    try:
        # 1. 初始化数据库
        print("1️⃣  初始化数据库连接...")
        await connect.init()
        print("   ✅ 数据库连接成功")
        print()
        
        # 2. 获取初始状态
        print("2️⃣  获取当前迁移状态...")
        status = await get_migration_status()
        print(f"   📊 数据库类型: {status['db_type']}")
        print(f"   📌 当前版本: v{status['current_version']}")
        print(f"   🎯 目标版本: v{status['target_version']}")
        print(f"   ⏳ 待执行迁移: {status['migrations_count']} 个")
        print()
        
        # 3. 执行迁移
        if status['migrations_count'] > 0:
            print("3️⃣  执行自动迁移...")
            result = await auto_migrate(silent=False)
            if result:
                print("   ✅ 迁移执行成功")
            else:
                print("   ℹ️  无需迁移")
        else:
            print("3️⃣  数据库已是最新版本，无需迁移")
            print("   ✅ 跳过")
        print()
        
        # 4. 验证最终状态
        print("4️⃣  验证最终状态...")
        final_status = await get_migration_status()
        print(f"   📌 最终版本: v{final_status['current_version']}")
        
        if final_status['is_up_to_date']:
            print("   ✅ 数据库版本正确")
        else:
            print("   ❌ 数据库版本不正确")
            return False
        print()
        
        # 5. 测试版本表
        print("5️⃣  测试版本表...")
        from tortoise import Tortoise
        conn = Tortoise.get_connection("default")
        
        try:
            result = await conn.execute_query(
                "SELECT COUNT(*) FROM db_version"
            )
            count = result[1][0][0]
            print(f"   📝 版本记录数: {count}")
            print("   ✅ 版本表正常")
        except Exception as e:
            print(f"   ❌ 版本表异常: {e}")
            return False
        print()
        
        # 6. 测试新表
        print("6️⃣  测试新创建的表...")
        tables_to_check = ["mai_maps", "mai_map_treasures"]
        
        for table_name in tables_to_check:
            try:
                result = await conn.execute_query(
                    f"SELECT COUNT(*) FROM {table_name}"
                )
                print(f"   ✅ 表 {table_name} 存在且可访问")
            except Exception as e:
                print(f"   ❌ 表 {table_name} 测试失败: {e}")
                return False
        print()
        
        # 7. 测试 mai_songs 新字段
        print("7️⃣  测试 mai_songs 表的新字段...")
        try:
            result = await conn.execute_query(
                "SELECT mai_map FROM mai_songs LIMIT 1"
            )
            print("   ✅ mai_map 字段存在且可访问")
        except Exception as e:
            print(f"   ❌ mai_map 字段测试失败: {e}")
            return False
        print()
        
        print("=" * 70)
        print(" 🎉 所有测试通过！迁移系统工作正常 ".center(70, "="))
        print("=" * 70)
        return True
        
    except Exception as e:
        print()
        print("=" * 70)
        print(f"❌ 测试失败: {e}")
        print("=" * 70)
        import traceback
        traceback.print_exc()
        return False
        
    finally:
        await connect.close()


if __name__ == "__main__":
    success = asyncio.run(test_migration())
    sys.exit(0 if success else 1)
