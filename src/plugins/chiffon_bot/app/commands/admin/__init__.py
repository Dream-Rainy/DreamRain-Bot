"""Global admin commands for chiffon_bot."""

from __future__ import annotations

import json
from pathlib import Path

from nonebot.adapters import Event, Message
from nonebot.params import CommandArg
from nonebot.permission import SUPERUSER

from ....integrations.lxns.client import lxns_client
from ....shared.game.registry import iter_domain_adapters
from ....shared.search.embedding_cache import embedding_status
from ....shared.search.search_audit import (
    alias_candidate_from_row,
    get_search_history_row,
    import_alias_candidates,
    list_alias_candidates,
    update_alias_candidate_status,
)


def _search_help() -> str:
    return (
        "搜索审核命令：\n"
        "/admin.search pending [数量]\n"
        "/admin.search show <编号>\n"
        "/admin.search accept <编号>\n"
        "/admin.search reject <编号>\n"
        "/admin.search export accepted [数量]\n"
        "/admin.search import <JSONL路径>\n"
        "/admin.search embedding status\n"
        "/admin.search embedding rebuild <game>"
    )


def _parse_limit(value: str | None, default: int = 10) -> int:
    if not value:
        return default
    try:
        return max(1, min(int(value), 50))
    except ValueError:
        return default


def _format_candidate(candidate: dict, index: int | None = None) -> str:
    prefix = f"{index}. " if index is not None else ""
    evidence = candidate.get("evidence") or {}
    score = evidence.get("top_score")
    if score is None:
        score = evidence.get("musicbrainz_score")
    match_type = evidence.get("top_match_type") or candidate.get("source")
    return (
        f"{prefix}#{candidate.get('line')} {candidate.get('game')} "
        f"{candidate.get('alias')!r} -> [{candidate.get('song_id')}] "
        f"{candidate.get('title')} "
        f"score={score} "
        f"type={match_type} "
        f"status={candidate.get('status')}"
    )


def _format_history_row(row: dict) -> str:
    candidate = alias_candidate_from_row(row)
    lines = [
        f"#{row.get('_line')} {row.get('game')} query={row.get('query')!r}",
        f"top=[{row.get('top_song_id')}] score={row.get('top_score')} type={row.get('top_match_type')}",
        f"trace={row.get('trace_id')}",
    ]
    if candidate:
        lines.append(_format_candidate(candidate))
    results = row.get("results") or []
    if results:
        lines.append("结果：")
        lines.extend(
            f"{item.get('rank')}. [{item.get('song_id')}] {item.get('title')} "
            f"score={item.get('score')} type={item.get('match_type')}"
            for item in results[:5]
        )
    return "\n".join(lines)


def _format_embedding_status() -> str:
    status = embedding_status()
    songs = status["songs"] or {}
    song_text = "，".join(f"{game}: {count}" for game, count in songs.items()) or "无"
    models = "，".join(status["models"]) or "无"
    return (
        "Embedding 缓存状态：\n"
        f"path={status['path']}\n"
        f"exists={status['exists']}\n"
        f"songs={song_text}\n"
        f"models={models}"
    )


def register_admin_commands(admin_group) -> None:
    """Register cross-domain admin commands."""

    update_cmd = admin_group.command("update", force_whitespace=True, permission=SUPERUSER)

    @update_cmd.handle()
    async def _update():
        try:
            _is_updated, message = await lxns_client.catalog.refresh_song_data(manual=True)
        except Exception as e:
            message = f"更新失败: {e}"
        await update_cmd.finish(message)

    clean_cmd = admin_group.command("clean", force_whitespace=True, permission=SUPERUSER)

    @clean_cmd.handle()
    async def _clean():
        adapters = iter_domain_adapters()
        for adapter in adapters:
            adapter.clear_image_cache()

        names = "、".join(adapter.display_name for adapter in adapters) or "无"
        await clean_cmd.finish(f"已清除以下 domain 的图片缓存：{names}")

    search_cmd = admin_group.command("search", force_whitespace=True, permission=SUPERUSER)

    @search_cmd.handle()
    async def _search(event: Event, args: Message = CommandArg()):
        text = args.extract_plain_text().strip()
        parts = text.split()
        if not parts:
            await search_cmd.finish(_search_help())

        action = parts[0].lower()
        try:
            if action == "pending":
                limit = _parse_limit(parts[1] if len(parts) > 1 else None)
                candidates = list_alias_candidates(status="pending", limit=limit)
                if not candidates:
                    await search_cmd.finish("暂无待审核搜索候选。")
                lines = ["待审核搜索候选："]
                lines.extend(_format_candidate(candidate, idx) for idx, candidate in enumerate(candidates, start=1))
                await search_cmd.finish("\n".join(lines))

            if action == "show" and len(parts) >= 2:
                row = get_search_history_row(int(parts[1]))
                if row is None:
                    await search_cmd.finish(f"未找到搜索记录 #{parts[1]}")
                await search_cmd.finish(_format_history_row(row))

            if action in {"accept", "reject"} and len(parts) >= 2:
                status = "accepted" if action == "accept" else "rejected"
                candidate = update_alias_candidate_status(
                    int(parts[1]),
                    status,
                    reviewer=event.get_user_id(),
                )
                game = str(candidate.get("game") or "").strip()
                if game:
                    lxns_client.catalog.invalidate_alias_cache(game)
                await search_cmd.finish(f"已标记为 {status}：\n{_format_candidate(candidate)}")

            if action == "export":
                status = parts[1].lower() if len(parts) > 1 else "accepted"
                if status not in {"pending", "accepted", "rejected", "all"}:
                    await search_cmd.finish("export 状态只能是 pending / accepted / rejected / all")
                limit = _parse_limit(parts[2] if len(parts) > 2 else None, default=20)
                candidates = list_alias_candidates(status=status, limit=limit)
                if not candidates:
                    await search_cmd.finish(f"暂无 {status} 搜索候选。")
                payload = [
                    {
                        key: value
                        for key, value in candidate.items()
                        if key != "line"
                    }
                    for candidate in candidates
                ]
                text = "\n".join(json.dumps(item, ensure_ascii=False, sort_keys=True) for item in payload)
                await search_cmd.finish(text)

            if action == "import":
                source = text.partition(" ")[2].strip().strip('"')
                if not source:
                    await search_cmd.finish("请输入 JSONL 路径，例如：/admin.search import docs/ai/mb-candidates.jsonl")
                source_path = Path(source)
                if not source_path.exists():
                    await search_cmd.finish(f"JSONL 文件不存在：{source_path}")
                count = import_alias_candidates(source_path)
                await search_cmd.finish(f"已导入 {count} 条 pending 搜索候选。")

            if action == "embedding":
                sub_action = parts[1].lower() if len(parts) > 1 else "status"
                if sub_action == "status":
                    await search_cmd.finish(_format_embedding_status())
                if sub_action == "rebuild" and len(parts) >= 3:
                    try:
                        result = await lxns_client.catalog.rebuild_search_embeddings(parts[2])
                    except Exception as exc:
                        await search_cmd.finish(f"embedding rebuild 失败：{exc}")
                    await search_cmd.finish(
                        f"已重建 {result['game']} embedding 缓存："
                        f"{result['songs']} 首，model={result['model']}，path={result['path']}"
                    )
                await search_cmd.finish("用法：/admin.search embedding status 或 /admin.search embedding rebuild <game>")
        except ValueError as exc:
            await search_cmd.finish(str(exc))

        await search_cmd.finish(_search_help())
