from nonebot import get_driver, on_command
from nonebot.adapters import Event, Message
from nonebot.params import CommandArg
from nonebot.permission import SUPERUSER
from nonebot.plugin import PluginMetadata

from src.plugins.platform_adapter.context import PlatformContext

from .config import Config, plugin_config
from .core import get_permission_manager
from .privilege import PrivilegeLevel, level_name

# ── 自初始化：插件加载后自动完成权限表加载和 Matcher 守卫安装 ──

_driver = get_driver()


@_driver.on_startup
async def _init_permission_admin():
    from .core import install_global_matcher_guard, load_permission_store

    load_permission_store()
    install_global_matcher_guard()

__plugin_meta__ = PluginMetadata(
    name="permission_admin",
    description="按群/用户禁用插件（SUPERUSER）；默认全群全用户可用",
    config=Config,
    usage=(
        "perm — 帮助\n"
        "perm list — 在群内查看各插件在本群是否可用（✓/✗）\n"
        "perm on|off <plugin_id> — 在当前群恢复/禁用该插件（须群内）\n"
        "perm glob|g on|off <plugin_id> <目标群号> — 在控制台群内远程设置（须配置 control_groups）\n"
        "perm user on|off <plugin_id> <uid> — 对指定用户恢复/禁用该插件\n"
        "perm wl <plugin_id> — 查看已禁用群号/用户列表\n"
        "perm clear <plugin_id> — 清除该插件全部群和用户的禁用\n"
        "perm matchers <plugin_id> — 列出插件所有 matcher 的 handler 名\n"
        "perm level list|set|reset — 管理 matcher 级最低特权等级\n"
        "perm blacklist add|del|list — 管理全局黑名单\n"
        "perm whitelist add|del|list — 管理全局白名单"
    ),
)

_cmd = on_command("perm", permission=SUPERUSER, priority=1, block=True)

_TICK = "✓"
_CROSS = "✗"


def _help() -> str:
    return (
        "[perm] SUPERUSER\n"
        "perm list\n"
        "perm on|off <plugin_id>（在目标群内发送）\n"
        "perm glob|g on|off <plugin_id> <目标群号>（须在控制台群，见 control_groups）\n"
        "perm user on|off <plugin_id> <uid>\n"
        "perm wl <plugin_id>\n"
        "perm clear <plugin_id>\n"
        "perm matchers <plugin_id>\n"
        "perm level list|set <pid> <handler> <level>|reset <pid> <handler>\n"
        "perm blacklist add|del <uid> | list\n"
        "perm whitelist add|del <uid> | list"
    )


@_cmd.handle()
async def _(event: Event, args: Message = CommandArg()) -> None:
    ctx = PlatformContext.from_event(event)
    parts = args.extract_plain_text().strip().split()
    if not parts:
        await _cmd.finish(_help())

    mgr = get_permission_manager()
    sub = parts[0].lower()

    if sub in ("help", "h", "帮助"):
        await _cmd.finish(_help())

    if sub == "reload":
        summary = mgr.reload_from_disk()
        lines = [f"权限表已重载：共 {summary['loaded_plugins']} 个插件有禁用记录"]
        if summary["added"]:
            lines.append(f"新增：{', '.join(summary['added'])}")
        if summary["removed"]:
            lines.append(f"移除：{', '.join(summary['removed'])}")
        await _cmd.finish("\n".join(lines))

    if sub == "list":
        if not ctx.is_group:
            await _cmd.finish("perm list 请在群内使用，以查看各插件在本群是否可用。")
        if len(parts) >= 2:
            try:
                target_gid = int(parts[1])
            except ValueError:
                await _cmd.finish("群号无效")
            control = set(plugin_config.control_groups)
            if not control:
                await _cmd.finish(
                    "未配置 permission_admin_control_groups，"
                    "已禁用 perm list <群号>。"
                )
            here = ctx.require_group_id()
            if here not in control:
                await _cmd.finish(
                    f"当前群 {here} 不是控制台群，无法查看其他群状态。"
                )
            gid = target_gid
            header = f"群 {gid}"
        else:
            gid = ctx.require_group_id()
            header = f"当前群 {gid}"
        rows = mgr.list_loaded_plugins_for_group(gid)
        if not rows:
            await _cmd.finish("当前没有已加载的插件。")
        lines = [
            f"{header}：✓=可用 ✗=已禁用（perm off <id>）"
        ]
        for row in rows:
            sym = _TICK if row["available"] else _CROSS
            lines.append(f"- {row['plugin_id']} {sym}")
        await _cmd.finish("\n".join(lines))

    if sub in ("on", "off"):
        if len(parts) < 2:
            await _cmd.finish("用法：perm on|off <plugin_id>（请在目标群内发送）")
        if not ctx.is_group:
            await _cmd.finish("请在需要操作的群聊内发送本命令。")
        pid = parts[1]
        if not mgr.is_plugin_loaded(pid):
            await _cmd.finish(f"插件 {pid} 不存在，请使用 perm list 查看可用的插件 ID。")
        gid = ctx.require_group_id()
        if sub == "off":
            if pid == "permission_admin":
                await _cmd.finish("permission_admin 不可禁用自身，该插件始终可用。")
            mgr.block_in_group(pid, gid)
            await _cmd.finish(f"已在当前群禁用：{pid}")
        else:
            mgr.unblock_in_group(pid, gid)
            await _cmd.finish(f"已在当前群恢复：{pid}")

    if sub in ("glob", "g"):
        if len(parts) < 4:
            await _cmd.finish(
                "用法：perm glob on|off <plugin_id> <目标群号>\n"
                "须在配置项 control_groups 内的控制台群中发送。"
            )
        action = parts[1].lower()
        if action not in ("on", "off"):
            await _cmd.finish("用法：perm glob on|off <plugin_id> <目标群号>")
        pid = parts[2]
        if not mgr.is_plugin_loaded(pid):
            await _cmd.finish(f"插件 {pid} 不存在，请使用 perm list 查看可用的插件 ID。")
        try:
            target_gid = int(parts[3])
        except ValueError:
            await _cmd.finish("目标群号无效")
        if not ctx.is_group:
            await _cmd.finish("远程设置也须在群聊内发送（控制台群）。")
        control = set(plugin_config.control_groups)
        if not control:
            await _cmd.finish(
                "未配置 permission_admin_control_groups，已禁用 perm glob。"
                "在 .env 中设置后再试。"
            )
        here = ctx.require_group_id()
        if here not in control:
            await _cmd.finish(f"当前群 {here} 不是控制台群，无法使用 perm glob。")
        if action == "off":
            if pid == "permission_admin":
                await _cmd.finish("permission_admin 不可禁用自身，该插件始终可用。")
            mgr.block_in_group(pid, target_gid)
            await _cmd.finish(f"已在群 {target_gid} 禁用：{pid}")
        else:
            mgr.unblock_in_group(pid, target_gid)
            await _cmd.finish(f"已在群 {target_gid} 恢复：{pid}")

    if sub == "user":
        if len(parts) < 4:
            await _cmd.finish("用法：perm user on|off <plugin_id> <uid>")
        action = parts[1].lower()
        if action not in ("on", "off"):
            await _cmd.finish("用法：perm user on|off <plugin_id> <uid>")
        pid = parts[2]
        if not mgr.is_plugin_loaded(pid):
            await _cmd.finish(f"插件 {pid} 不存在，请使用 perm list 查看可用的插件 ID。")
        try:
            target_uid = int(parts[3])
        except ValueError:
            await _cmd.finish("UID 无效")
        if action == "off":
            if pid == "permission_admin":
                await _cmd.finish("permission_admin 不可禁用自身，该插件始终可用。")
            mgr.block_user(pid, target_uid)
            await _cmd.finish(f"已对用户 {target_uid} 禁用：{pid}")
        else:
            mgr.unblock_user(pid, target_uid)
            await _cmd.finish(f"已对用户 {target_uid} 恢复：{pid}")

    if sub == "clear":
        if len(parts) < 2:
            await _cmd.finish("用法：perm clear <plugin_id>")
        mgr.clear_blocks(parts[1])
        await _cmd.finish(f"已清除禁用记录：{parts[1]}")

    if sub == "wl":
        if len(parts) < 2:
            await _cmd.finish("用法：perm wl <plugin_id>")
        pid = parts[1]
        snap = mgr.get_snapshot(pid)
        if snap is None:
            await _cmd.finish(f"{pid}：当前没有已禁用的群或用户，也没有 matcher 等级配置")
        lines = [f"{pid}："]
        if snap.get("blocked_groups"):
            lines.append(f"已禁用群：{','.join(str(x) for x in snap['blocked_groups'])}")
        if snap.get("blocked_users"):
            lines.append(f"已禁用用户：{','.join(str(x) for x in snap['blocked_users'])}")
        if snap.get("matcher_levels"):
            ml_lines = [
                f"  {name}: {level_name(lvl)} ({lvl})"
                for name, lvl in snap["matcher_levels"].items()
            ]
            lines.append("matcher 等级：\n" + "\n".join(ml_lines))
        await _cmd.finish("\n".join(lines))

    # ── matchers ──────────────────────────────────────────────

    if sub == "matchers":
        if len(parts) < 2:
            await _cmd.finish("用法：perm matchers <plugin_id>")
        from nonebot.matcher import matchers

        pid = parts[1]
        if not mgr.is_plugin_loaded(pid):
            await _cmd.finish(f"插件 {pid} 不存在。")
        lines = [f"{pid}："]
        found = 0
        for priority_list in matchers.values():
            for m in priority_list:
                m_pid = getattr(m, "plugin_id", None)
                if m_pid != pid:
                    continue
                m_type = getattr(m, "type", "?")
                m_priority = getattr(m, "priority", "?")
                h_names = [h.call.__name__ for h in m.handlers] if m.handlers else ["(无 handler)"]
                for hn in h_names:
                    lines.append(f"  - {hn} [type={m_type}, priority={m_priority}]")
                found += 1
        if not found:
            lines.append("  (无 matcher)")
        await _cmd.finish("\n".join(lines))

    # ── level ─────────────────────────────────────────────────

    if sub == "level":
        if len(parts) < 2:
            await _cmd.finish(
                "用法：\n"
                "perm level list <plugin_id>\n"
                "perm level set <plugin_id> <handler_name> <level>\n"
                "perm level reset <plugin_id> <handler_name>"
            )
        action = parts[1].lower()
        if action == "list":
            if len(parts) < 3:
                await _cmd.finish("用法：perm level list <plugin_id>")
            pid = parts[2]
            levels = mgr.get_matcher_levels(pid)
            if not levels:
                await _cmd.finish(f"{pid}：无 matcher 等级配置")
            lines = [f"{pid} matcher 等级："]
            for name, lvl in sorted(levels.items()):
                lines.append(f"  {name}: {level_name(lvl)} ({lvl})")
            await _cmd.finish("\n".join(lines))

        if action in ("set", "reset"):
            if len(parts) < 3:
                await _cmd.finish(f"用法：perm level {action} <plugin_id> <handler_name> [level]")
            pid = parts[2]
            if not mgr.is_plugin_loaded(pid):
                await _cmd.finish(f"插件 {pid} 不存在。")
            if len(parts) < 4:
                await _cmd.finish(f"用法：perm level {action} <plugin_id> <handler_name> [level]")
            handler_name = parts[3]
            if action == "set":
                if len(parts) < 5:
                    await _cmd.finish("用法：perm level set <plugin_id> <handler_name> <level>")
                lvl = PrivilegeLevel.from_string(parts[4])
                if lvl is None:
                    await _cmd.finish(
                        f"无效等级：{parts[4]}。可用：BLACK, DEFAULT, NORMAL, PRIVATE, ADMIN, OWNER, WHITE, SUPERUSER"
                    )
                mgr.set_matcher_level(pid, handler_name, lvl.value)
                await _cmd.finish(f"已设置 {pid}/{handler_name} → {level_name(lvl.value)} ({lvl.value})")
            else:
                mgr.reset_matcher_level(pid, handler_name)
                await _cmd.finish(f"已重置 {pid}/{handler_name} 的等级配置")
            return

        await _cmd.finish(
            "用法：perm level list|set|reset ..."
        )

    # ── blacklist ─────────────────────────────────────────────

    if sub == "blacklist":
        if len(parts) < 2:
            await _cmd.finish("用法：perm blacklist add|del <uid> | list")
        action = parts[1].lower()
        if action == "list":
            bl = mgr.get_blacklist()
            if not bl:
                await _cmd.finish("全局黑名单为空")
            await _cmd.finish(f"全局黑名单：{','.join(str(x) for x in bl)}")
        if action in ("add", "del"):
            if len(parts) < 3:
                await _cmd.finish(f"用法：perm blacklist {action} <uid>")
            try:
                uid = int(parts[2])
            except ValueError:
                await _cmd.finish("UID 无效")
            if action == "add":
                mgr.add_to_blacklist(uid)
                await _cmd.finish(f"已添加 {uid} 到全局黑名单")
            else:
                mgr.remove_from_blacklist(uid)
                await _cmd.finish(f"已从全局黑名单移除 {uid}")
            return
        await _cmd.finish("用法：perm blacklist add|del <uid> | list")

    # ── whitelist ─────────────────────────────────────────────

    if sub == "whitelist":
        if len(parts) < 2:
            await _cmd.finish("用法：perm whitelist add|del <uid> | list")
        action = parts[1].lower()
        if action == "list":
            wl = mgr.get_whitelist()
            if not wl:
                await _cmd.finish("全局白名单为空")
            await _cmd.finish(f"全局白名单：{','.join(str(x) for x in wl)}")
        if action in ("add", "del"):
            if len(parts) < 3:
                await _cmd.finish(f"用法：perm whitelist {action} <uid>")
            try:
                uid = int(parts[2])
            except ValueError:
                await _cmd.finish("UID 无效")
            if action == "add":
                mgr.add_to_whitelist(uid)
                await _cmd.finish(f"已添加 {uid} 到全局白名单")
            else:
                mgr.remove_from_whitelist(uid)
                await _cmd.finish(f"已从全局白名单移除 {uid}")
            return
        await _cmd.finish("用法：perm whitelist add|del <uid> | list")

    await _cmd.finish(_help())
