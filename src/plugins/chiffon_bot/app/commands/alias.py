"""Thin command bridge to arcade-helper's authenticated alias service."""

from __future__ import annotations

import json
import shlex
from hashlib import sha256
from uuid import uuid4

from arcade_helper.core.errors import ArcadeHelperError
from arcade_helper.aliases import AliasCandidate
from arcade_helper.storage.tortoise.catalog_models import GameSong
from nonebot.adapters import Bot, Event, Message
from nonebot.params import CommandArg
from nonebot.permission import SUPERUSER
from nonebot import logger
from tortoise.exceptions import DoesNotExist

from ...integrations.lxns.client import lxns_client
from ...shared.bot_response import BotResponse
from ...shared.search.timing import stage
from ._response import finish_with


_USER_HELP = (
    "/arcade.alias <game> <歌曲ID或名称>\n"
    "/arcade.alias add [游戏] <曲名/已有别名/ID> <新别名>\n"
    "/arcade.alias request <请求ID>\n"
    "/arcade.alias withdraw <请求ID> <版本>\n"
    "指定游戏仅作用于所选收录；省略游戏则同作品共享。\n"
    "含空格的查询词用引号包住。提交后等待审核。"
)
_ADMIN_HELP = (
    "/admin.alias pending [上一页末尾请求ID]\n/admin.alias show <请求ID>\n"
    "/admin.alias approve|reject <请求ID> <版本> <理由>\n"
    "/admin.alias confirm <请求ID> <版本> <目标版本JSON> <理由>\n"
    "/admin.alias retract <证据ID> <理由>\n"
    "/admin.alias replace <证据ID> <game> <歌曲ID> <work|game_song> <新别名>\n"
    "/admin.alias block|unblock <game> <歌曲ID> <别名>\n"
    "/admin.alias relink <merge|split> <内部收录ID,内部收录ID> <理由>\n"
    "/admin.alias candidates [游标]\n"
    "/admin.alias decide <候选ID> <版本> <accept|reject> <理由>\n"
    "/admin.alias sync <game>\n"
    "/admin.alias imports <game>\n"
    "/admin.alias map <game> <provider> <namespace> <external_key> <bind|new|reject> <内部收录ID或-> <理由>\n"
    "/admin.alias source <来源键> <game或global> <enable|disable>"
)


def _detail_text(detail: dict) -> str:
    return (
        f"请求 #{detail['id']} v{detail['version']} {detail['status']} {detail['operation']}\n"
        f"内容：{json.dumps(detail['payload'], ensure_ascii=False)}\n"
        f"理由：{detail['reason']}\n"
        f"影响游戏：{', '.join(detail['affected_games'])}\n"
        f"可审核：{detail['can_review']} {detail['review_blocked_reason'] or ''}\n"
        f"同名候选：{json.dumps(detail['same_alias_candidates'], ensure_ascii=False)}\n"
        f"目标版本：{json.dumps(detail['current_target_versions'], separators=(',', ':'))}\n"
        f"处理理由：{detail['decision_reason'] or ''}"
    )


async def _alias_candidates(game: str, query: str) -> list[AliasCandidate]:
    return list((await lxns_client.catalog.search_all(query, game_code=game, allow_semantic=False)).candidates)


async def alias_query_text(game: str, query: str) -> str:
    with stage("alias.resolve"):
        results = await _alias_candidates(game, query)
    exact = [r for r in results if r.match_type.startswith("exact_")]
    choices = exact or results
    if not choices:
        return f"未找到 {game} 歌曲；通用曲库须先由管理员 /admin.alias sync {game} 导入。"
    if len(choices) != 1 or not exact:
        displayed = choices[:10]
        ids = await lxns_client.catalog.public_song_ids([(game, r.game_song_id) for r in displayed])
        lines = [f"[{ids[(game, r.game_song_id)]}] {r.title}" for r in displayed]
        return "请使用明确的歌曲 ID 查询：\n" + "\n".join(lines)
    song = choices[0]
    internal_id = song.game_song_id
    song_id = await lxns_client.catalog.public_song_id(game, internal_id)
    with stage("alias.evidence"):
        evidence = await lxns_client.data.aliases.get_effective_aliases(internal_id)
    lines = [f"[{game}] [{song_id}] {song.title}（内部收录 #{internal_id}）"]
    groups = {}
    for item in evidence:
        if item['kind'] != 'alias':
            continue
        group = groups.setdefault((item['alias_key'], item['scope']), {"text": item['text'], "sources": []})
        if item['source_key'] not in group['sources']:
            group['sources'].append(item['source_key'])
    lines.extend(
        f"{group['text']} | {scope} | 来源 {'、'.join(group['sources'])}"
        for (_, scope), group in groups.items()
    )
    if len(lines) == 1:
        lines.append("暂无有效别名")
    return "\n".join(lines)


async def _submit(bot: Bot, event: Event, actor: int, operation: str, payload: dict, reason: str = "") -> str:
    context_key = f"{bot.self_id}:{event.get_session_id()}:{event.get_event_name()}:{getattr(event, 'message_id', '')}"
    # Some adapters have no message ID; command content keeps different requests distinct.
    key = sha256((context_key + event.get_plaintext()).encode()).hexdigest() if getattr(event, 'message_id', None) is not None else uuid4().hex
    request_id = await lxns_client.data.aliases.submit(
        actor_id=actor, operation=operation, payload=payload,
        idempotency_key=key, reason=reason,
    )
    return f"已提交请求 #{request_id}，审核通过前不会生效。"


async def _add_alias(text: str, bot: Bot, event: Event, actor: int) -> str:
    from ...shared.game.registry import iter_searchable_adapters
    from .natural_language import _choice_tokens, _wait_for_choice_text

    fields = shlex.split(text)[1:]
    games = {code: code for code in await GameSong.filter(active=True).distinct().values_list("game_code", flat=True)}
    for adapter in iter_searchable_adapters():
        games.update({token: adapter.game_code for token in _choice_tokens(adapter)})
    game = games.get(fields[0].lower()) if fields else None
    if game:
        fields = fields[1:]
    if len(fields) < 2:
        return _USER_HELP
    query, alias = fields[0], " ".join(fields[1:])

    if game:
        candidates = await _alias_candidates(game, query)
    else:
        candidates = list((await lxns_client.catalog.search_all(query, allow_semantic=False)).candidates)
    exact = [candidate for candidate in candidates if candidate.match_type.startswith("exact_")]
    matches = exact or candidates
    if not matches:
        return "未找到匹配的歌曲，请检查查询词或先导入曲库。"
    if game:
        choices = matches
    else:
        works = {}
        for candidate in matches:
            works.setdefault(candidate.work_id, candidate)
        choices = list(works.values())

    if len(choices) != 1 or not exact:
        lines = ["请选择要添加别名的目标，回复序号："]
        for index, candidate in enumerate(choices[:10], start=1):
            song_id = await lxns_client.catalog.public_song_id(candidate.game_code, candidate.game_song_id)
            codes = [candidate.game_code] if game else list(dict.fromkeys(c.game_code for c in matches if c.work_id == candidate.work_id))
            lines.append(f"{index}. [{' / '.join(codes)}] [{song_id}] {candidate.title} ({candidate.score:.0f}%)")
        if len(choices) > 10:
            lines.append(f"还有 {len(choices) - 10} 个目标，可缩小查询范围后重试。")
        selected = await _wait_for_choice_text(
            event=event, prompt=BotResponse(text="\n".join(lines), reply_to=getattr(event, "message_id", None)),
        )
        if selected is None or not selected.isdecimal() or not 1 <= int(selected) <= min(10, len(choices)):
            return "没有识别到要添加别名的目标，已取消。"
        candidate = choices[int(selected) - 1]
    else:
        candidate = choices[0]
    return await _submit(bot, event, actor, "ADD_ALIAS", {
        "game_song_id": candidate.game_song_id, "text": alias,
        "scope": "game_song" if game else "work", "origin_game": game,
    })


async def handle_alias_command(text: str, bot: Bot, event: Event, *, admin: bool = False) -> str:
    parts = text.strip().split()
    if not parts:
        return _ADMIN_HELP if admin else _USER_HELP
    service = lxns_client.data.aliases
    action = parts[0].lower()
    try:
        if not admin and action not in {"add", "request", "withdraw"}:
            game, query = text.strip().split(maxsplit=1)
            return await alias_query_text(game.lower(), query)
        actor = await lxns_client.alias_actor(bot, event)
        if admin and not await SUPERUSER(bot, event):
            return "需要 SUPERUSER 权限"
        if action in {"request", "show"} and len(parts) == 2:
            return _detail_text(await service.get_request(int(parts[1]), actor_id=actor))
        if action == "withdraw" and len(parts) == 3 and not admin:
            await service.withdraw(int(parts[1]), actor_id=actor, expected_version=int(parts[2]))
            return "已撤回请求"
        if action == "add":
            return await _add_alias(text, bot, event, actor)
        if action in {"block", "unblock"} and admin:
            fields = text.strip().split(maxsplit=3)
            if len(fields) != 4:
                return _ADMIN_HELP if admin else _USER_HELP
            game, song_id = fields[1].lower(), int(fields[2])
            internal_id = await lxns_client.catalog.internal_song_id(game, song_id)
            payload = {"game_song_id": internal_id, "text": fields[-1]}
            operation = {"block": "BLOCK_ALIAS", "unblock": "UNBLOCK_ALIAS"}[action]
            return await _submit(bot, event, actor, operation, payload)
        if not admin:
            return _USER_HELP
        if action == "pending" and len(parts) <= 2:
            page = await service.list_requests(actor_id=actor, after_id=int(parts[1]) if len(parts) == 2 else 0,
                                               limit=20, include_details=False)
            lines = []
            for detail in page['items']:
                payload = detail['payload']
                targets = "、".join(f"[{s['game_code']}] {s['title']}" for s in detail['songs']) or "来源记录"
                text = f" → {payload['text']}" if 'text' in payload else ""
                scope = {"work": "（跨游戏）", "game_song": "（仅此游戏）"}.get(payload.get('scope'), "")
                operation = "" if detail['operation'] == 'ADD_ALIAS' else f"{detail['operation']} "
                lines.append(f"#{detail['id']} v{detail['version']} {operation}{targets}{text}{scope}")
            if lines:
                lines.append("\n详情：/admin.alias show <请求编号>")
            if page['has_more']:
                lines.append(f"下一页：/admin.alias pending {page['next_cursor']}")
            return "\n".join(lines or ["暂无可见的待审核请求"])
        if action in {"approve", "reject", "confirm"}:
            fields = text.strip().split(maxsplit=4 if action == "confirm" else 3)
            if len(fields) != (5 if action == "confirm" else 4):
                return _ADMIN_HELP
            targets = json.loads(fields[3]) if action == "confirm" else None
            await service.review(
                int(fields[1]), actor_id=actor, approve=action != "reject",
                expected_version=int(fields[2]), reason=fields[-1], expected_target_versions=targets,
            )
            return "审核完成"
        if action == "retract":
            fields = text.strip().split(maxsplit=2)
            if len(fields) == 3:
                return await _submit(bot, event, actor, "RETRACT_EVIDENCE", {"evidence_id": int(fields[1])}, fields[2])
        if action == "replace":
            fields = text.strip().split(maxsplit=5)
            if len(fields) == 6:
                game = fields[2].lower()
                return await _submit(bot, event, actor, "REPLACE_ALIAS", {
                    "evidence_id": int(fields[1]), "game_song_id": await lxns_client.catalog.internal_song_id(game, int(fields[3])),
                    "scope": fields[4], "text": fields[5], "origin_game": game,
                })
        if action == "relink":
            fields = text.strip().split(maxsplit=3)
            if len(fields) == 4:
                return await _submit(bot, event, actor, "RELINK_GAME_SONGS", {
                    "mode": fields[1], "song_ids": [int(s) for s in fields[2].split(',')],
                }, fields[3])
        if action == "candidates" and len(parts) <= 2:
            page = await service.list_candidates(actor_id=actor, after_id=int(parts[1]) if len(parts) == 2 else 0, limit=20)
            return json.dumps(page, ensure_ascii=False, default=str)
        if action == "decide":
            fields = text.strip().split(maxsplit=4)
            if len(fields) == 5 and fields[3] in {"accept", "reject"}:
                await service.decide_candidate(int(fields[1]), actor_id=actor, expected_version=int(fields[2]),
                                               accept=fields[3] == "accept", reason=fields[4])
                return "作品关联候选已处理"
        if action == "sync" and len(parts) == 2:
            game = parts[1].lower()
            if game in {"maimai", "chunithm"}:
                report = await lxns_client.data.catalog.sync_game_from_remote(game, include_songs=False)
                if not report.ok:
                    raise report.error or ValueError("曲库同步失败")
            else:
                report = await lxns_client.data.catalog.import_catalog(game)
            if game in {"maimai", "chunithm"}:
                count = len(await lxns_client.data.catalog.load_song_index(game))
                return f"曲库同步完成：{game}，{count} 首"
            return f"曲库同步完成：{game}，新增 {report.created}，更新 {report.updated}，待定 {len(report.pending)}，无效 {len(report.invalid)}"
        if action == "imports" and len(parts) == 2:
            return json.dumps(await lxns_client.identities.get_import(parts[1].lower()), ensure_ascii=False, default=str)
        if action == "map":
            fields = text.strip().split(maxsplit=7)
            if len(fields) == 8:
                payload = dict(game_code=fields[1].lower(), provider=fields[2], namespace=fields[3],
                               external_key=fields[4], decision=fields[5])
                if fields[5] == "bind":
                    payload["target_id"] = int(fields[6])
                elif fields[6] != "-":
                    raise ValueError("new/reject 的目标 ID 应写 -")
                return await _submit(bot, event, actor, "MAP_SOURCE_RECORD", payload, fields[7])
        if action == "source" and len(parts) == 4 and parts[3] in {"enable", "disable"}:
            from arcade_helper.storage.tortoise.alias_models import AliasSource
            current = await AliasSource.filter(source_key=parts[1]).first()
            await service.configure_source(parts[1], actor_id=actor,
                origin_game=None if parts[2] == "global" else parts[2], enabled=parts[3] == "enable",
                kind=current.kind if current else "external", trusted_import=current.trusted_import if current else False)
            return "来源状态已更新"
        return _ADMIN_HELP
    except (ValueError, KeyError, ArcadeHelperError, DoesNotExist) as exc:
        if "TARGET_CHANGED" in str(exc):
            return "目标已变化。请求审核请 /admin.alias show 查看影响，再使用 confirm 携带最新目标版本 JSON；作品关联候选请重新 /admin.alias candidates 查看。"
        return f"别名操作失败：{exc}"
    except Exception:
        logger.exception("别名命令服务异常")
        return "别名服务暂不可用，请管理员检查日志后重试。"


def register_alias_commands(arcade_group, admin_group) -> None:
    user_cmd = arcade_group.command("alias", force_whitespace=True)
    admin_cmd = admin_group.command("alias", force_whitespace=True, permission=SUPERUSER)

    @user_cmd.handle()
    async def _alias(bot: Bot, event: Event, args: Message = CommandArg()):
        await finish_with(BotResponse(text=await handle_alias_command(args.extract_plain_text(), bot, event)))

    @admin_cmd.handle()
    async def _admin_alias(bot: Bot, event: Event, args: Message = CommandArg()):
        await finish_with(BotResponse(text=await handle_alias_command(args.extract_plain_text(), bot, event, admin=True)))
