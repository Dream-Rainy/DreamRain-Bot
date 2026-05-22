import traceback
from tortoise import Tortoise

_ENGINE_BACKENDS: dict[str, str] = {
    "sqlite": "tortoise.backends.sqlite",
    "postgres": "tortoise.backends.asyncpg",
    "mysql": "tortoise.backends.mysql",
}


def _resolve_db_settings(*, db_url: str | None, db_settings: dict | None) -> dict:
    if db_settings is not None:
        return db_settings

    try:
        from ... import plugin_config

        engine = (plugin_config.db_engine or "sqlite").lower()
        backend = _ENGINE_BACKENDS.get(engine)
        if backend is None:
            raise ValueError(f"Unsupported db_engine: {engine}")

        credentials = dict(plugin_config.db_credentials or {})
        if engine == "sqlite":
            file_path = db_url or plugin_config.db_url or "data/chiffon_bot/db.sqlite3"
            credentials = {"file_path": file_path} | credentials

        return {"engine": backend, "credentials": credentials}
    except Exception as e:
        traceback.print_exc()
        print(f"Warning: Failed to load plugin_config (fallback to sqlite): {e}")
        file_path = db_url or "data/chiffon_bot/db.sqlite3"
        return {"engine": _ENGINE_BACKENDS["sqlite"], "credentials": {"file_path": file_path}}

async def init(*, db_url: str | None = None, db_settings: dict | None = None):
    db_settings = _resolve_db_settings(db_url=db_url, db_settings=db_settings)

    config = {
        "connections": {"default": db_settings},
        "apps": {
            "models": {
                "models": ["src.plugins.chiffon_bot.infra.db.models"],
                "default_connection": "default",
            }
        },
    }
    # 先初始化 Tortoise 连接（但不生成 schema）
    await Tortoise.init(config)
    
    # 在生成 schema 之前先执行数据库迁移
    # 这样可以确保所有必要的表结构变更都已完成
    try:
        from .migrations import auto_migrate
        migrated = await auto_migrate(silent=True)
        
        # 如果执行了迁移，说明是从旧版本升级，不需要 generate_schemas
        # 如果没有执行迁移，说明是新数据库或已是最新版本，需要 generate_schemas 确保表存在
        if not migrated:
            # 数据库已是最新版本，生成缺失的表（如果有）
            await Tortoise.generate_schemas()
    except Exception as e:
        print(f"Warning: Auto migration failed, falling back to generate_schemas: {e}")
        traceback.print_exc()
        # 如果迁移失败，回退到生成 schema（保持向后兼容）
        await Tortoise.generate_schemas()


async def close():
    await Tortoise.close_connections()
