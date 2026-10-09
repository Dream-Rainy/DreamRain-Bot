"""Preview catalog upgrades and migrate reviewed JSONL aliases explicitly."""

from __future__ import annotations

import argparse
import asyncio
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import unicodedata

from arcade_helper import ArcadeHelperClient
from arcade_helper.aliases.models import alias_key
from arcade_helper.storage.tortoise import (
    MODEL_MODULE, CATALOG_MODEL_MODULE, ALIAS_MODEL_MODULE,
    TortoiseAccountStore, TortoiseSongStore, TortoiseCatalogStore,
    upgrade_catalog_schema, initialize_catalog_storage, migrate_catalog_identities,
)
from arcade_helper.storage.tortoise.alias_models import AliasSource
from tortoise import Tortoise
from tortoise.utils import get_schema_sql


async def migrate_accepted_aliases(client, rows, *, actor_id=None, apply=False, mapping=None):
    """Require exact identity confirmation; never trust old generic enumeration IDs."""
    store = client.catalog.identities
    groups = defaultdict(list)
    report = {"ready": [], "unresolved": [], "ignored": 0, "applied": False}
    mapping = {} if mapping is None else mapping
    if not isinstance(mapping, dict) or any(not isinstance(key, str) or type(value) is not int or value <= 0 for key, value in mapping.items()):
        raise ValueError("mapping 必须是游戏:旧ID到正整数内部收录 ID 的 JSON 对象")
    normalize = lambda value: unicodedata.normalize("NFC", str(value or "")).strip()
    for line, row in enumerate(rows, 1):
        candidate = row.get("alias_candidate", row)
        if not isinstance(candidate, dict) or candidate.get("status", "pending") != "accepted":
            report["ignored"] += 1
            continue
        game = str(row.get("game") or candidate.get("game") or "").strip().lower()
        try:
            old_id = int(candidate["song_id"])
            if game in {"maimai", "chunithm"}:
                internal_id = await store.resolve_reference(game, str(old_id), provider="catalog", namespace="native")
            else:
                internal_id = mapping.get(f"{game}:{old_id}")
            song = await store.get_song_by_id(game, int(internal_id)) if internal_id is not None else None
            title = normalize(candidate.get("title"))
            if not title or song is None or normalize(song.title) != title:
                raise ValueError("旧 ID/标题未能对应当前收录；通用游戏需人工 mapping")
            artist = candidate.get("artist")
            if artist and normalize(song.artist) != normalize(artist):
                raise ValueError("作者不一致")
            text = str(candidate.get("alias") or row.get("query") or "").strip()
            normalized = alias_key(text)
            record_key = hashlib.sha256(json.dumps([game, old_id, title, normalized], ensure_ascii=False).encode()).hexdigest()
            groups[game].append({"anchor_id": song.id, "text": text, "record_key": record_key, "scope": "game_song"})
            report["ready"].append({"line": line, "game": game, "old_id": old_id, "game_song_id": song.id, "text": text})
        except (KeyError, TypeError, ValueError) as exc:
            report["unresolved"].append({"line": line, "game": game, "reason": str(exc)})
    if apply:
        if report["unresolved"]:
            raise ValueError("仍有身份不明的 accepted 记录；请先预览并补全 mapping，未写入任何别名")
        for game, observations in groups.items():
            key = f"bot-legacy:{game}"
            if not await AliasSource.filter(source_key=key).exists():
                await client.aliases.configure_source(key, actor_id=actor_id, origin_game=game,
                                                       kind="legacy", enabled=True, trusted_import=True)
            version = (await client.aliases.source_versions(game))[key]
            await client.aliases.sync_source(key, observations, actor_id=actor_id, expected_sync_version=version, complete=False)
        report["applied"] = True
    return report


def _read_jsonl(path):
    rows = []
    for line, text in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if text.strip():
            row = json.loads(text)
            if not isinstance(row, dict):
                raise ValueError(f"JSONL 第 {line} 行必须是对象")
            rows.append(row)
    return rows


async def _run(args):
    # Local maintenance still records a real configured administrator, not a supplied internal ID.
    import nonebot
    nonebot.init()
    if args.apply and (not args.actor or args.actor not in nonebot.get_driver().config.superusers):
        raise ValueError("--apply 需要 --actor 指定 .env SUPERUSERS 中的 QQ 账号")
    if not args.apply and args.db_url.startswith("sqlite://") and not Path(args.db_url[9:]).is_file():
        raise ValueError("预览需要已有的 SQLite 数据库副本，不创建空文件")
    await Tortoise.init(db_url=args.db_url, modules={"models": [MODEL_MODULE, CATALOG_MODEL_MODULE, ALIAS_MODEL_MODULE]})
    try:
        ddl = await upgrade_catalog_schema()
        print(json.dumps({"catalog_upgrade_ddl": ddl}, ensure_ascii=False))
        if args.schema_only:
            print(json.dumps({"create_if_missing_ddl": get_schema_sql(Tortoise.get_connection("default"), safe=True)}, ensure_ascii=False))
            if args.apply:
                await initialize_catalog_storage()
                await upgrade_catalog_schema(dry_run=False)
                print("catalog schema initialized")
            return
        if ddl:
            raise ValueError("请先备份数据库并执行 --schema-only --apply，再预览身份回填和别名迁移")
        store = TortoiseCatalogStore(enable_aliases=True)
        await store.get_revision()  # No table creation in a preview.
        backfill = await migrate_catalog_identities(store=store, dry_run=not args.apply)
        print(json.dumps({"native_backfill": {game: str(report) for game, report in backfill.items()}}, ensure_ascii=False))
        async def no_http(*_args, **_kwargs):
            raise RuntimeError("迁移不允许网络请求")
        administrators = set()
        client = ArcadeHelperClient(http_get_json=no_http, account_store=TortoiseAccountStore(),
                                    song_store=TortoiseSongStore(), catalog_store=store,
                                    alias_policy=lambda actor, action, game: actor in administrators)
        await client.lifecycle.start()
        actor_id = None
        if args.apply:
            user = await client.users.from_platform("qq", args.actor)
            actor_id = user.user_id
            administrators.add(actor_id)
        if args.input:
            rows = _read_jsonl(Path(args.input))
            mapping = json.loads(Path(args.mapping).read_text(encoding="utf-8")) if args.mapping else {}
            report = await migrate_accepted_aliases(client, rows, actor_id=actor_id, apply=args.apply, mapping=mapping)
            print(json.dumps(report, ensure_ascii=False, indent=2))
        await client.lifecycle.stop()
    finally:
        await Tortoise.close_connections()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-url", required=True, help="目标数据库 Tortoise URL；先在隔离副本演练")
    parser.add_argument("--schema-only", action="store_true")
    parser.add_argument("--input", help="旧审核结果 JSONL")
    parser.add_argument("--mapping", help='通用游戏人工 ID 映射 JSON，如 {"sdvx:1001":42}')
    parser.add_argument("--actor", help="执行迁移的 SUPERUSER QQ 账号")
    parser.add_argument("--apply", action="store_true", help="默认只预览；显式指定才执行")
    args = parser.parse_args()
    if args.schema_only and args.input:
        parser.error("表结构升级和 JSONL 导入应分开执行")
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
