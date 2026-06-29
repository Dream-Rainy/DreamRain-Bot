"""Global admin commands for chiffon_bot."""

from __future__ import annotations

from nonebot.permission import SUPERUSER

from ....integrations.lxns.client import lxns_client
from ....shared.game.registry import iter_domain_adapters


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
