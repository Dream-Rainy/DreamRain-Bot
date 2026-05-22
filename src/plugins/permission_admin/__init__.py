from nonebot import on_command
from nonebot.adapters import Event, Message
from nonebot.params import CommandArg
from nonebot.permission import SUPERUSER
from nonebot.plugin import PluginMetadata

from src.plugins.platform_adapter.context import PlatformContext

from .config import Config, plugin_config
from .core import get_permission_manager

__plugin_meta__ = PluginMetadata(
    name="permission_admin",
    description="按群禁用插件（SUPERUSER）；默认全群可用，群内 perm off 关闭当前群",
    config=Config,
    usage=(
        "perm — 帮助\n"
        "perm list — 在群内查看各插件在本群是否可用（✓/✗）\n"
        "perm on|off <plugin_id> — 在当前群恢复/禁用该插件（须群内）\n"
        "perm glob|g on|off <plugin_id> <目标群号> — 在控制台群内远程设置（须配置 control_groups）\n"
        "perm wl <plugin_id> — 查看已禁用群号列表\n"
        "perm clear <plugin_id> — 清除该插件全部群的禁用"
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
        "perm wl <plugin_id>\n"
        "perm clear <plugin_id>"
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
            mgr.block_in_group(pid, target_gid)
            await _cmd.finish(f"已在群 {target_gid} 禁用：{pid}")
        else:
            mgr.unblock_in_group(pid, target_gid)
            await _cmd.finish(f"已在群 {target_gid} 恢复：{pid}")

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
            await _cmd.finish(f"{pid}：当前没有已禁用的群")
        gids = snap["blocked_groups"]
        await _cmd.finish(f"{pid} 已禁用群：{','.join(str(x) for x in gids)}")

    await _cmd.finish(_help())
