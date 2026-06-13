from __future__ import annotations

from src.chiffon_data.integrations.lxns.accounts import StoredGameProfile

from ..account_store import TortoiseAccountStore


async def get_default_lxns_game_profile_by_qq(qq: str) -> StoredGameProfile | None:
    """通过 QQ 找到“默认”的 LXNS 账号对应的 GameProfile。

    选择策略（从强到弱）：
    1) UserAccount.is_default=True（同一 user + platform=lxns）
    2) 若仅存在一个 lxns 账号则用它
    3) 否则选 id 最大的 lxns 账号（最近创建）
    """
    return await TortoiseAccountStore().get_default_game_profile(qq)


async def set_default_lxns_account_for_qq(*, qq: str, lxns_account_key: str) -> None:
    await TortoiseAccountStore().set_default_lxns_account(qq=qq, account_key=lxns_account_key)
