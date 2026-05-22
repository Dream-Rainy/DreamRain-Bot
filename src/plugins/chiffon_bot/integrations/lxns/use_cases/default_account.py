from __future__ import annotations

from ....infra.db.models import QQ_PLATFORM, GameProfile, UserAccount
from ..session import LXNS_PLATFORM


async def get_default_lxns_game_profile_by_qq(qq: str) -> GameProfile | None:
    """通过 QQ 找到“默认”的 LXNS 账号对应的 GameProfile。

    选择策略（从强到弱）：
    1) UserAccount.is_default=True（同一 user + platform=lxns）
    2) 若仅存在一个 lxns 账号则用它
    3) 否则选 id 最大的 lxns 账号（最近创建）
    """

    qq_link = await UserAccount.get_or_none(platform=QQ_PLATFORM, account_key=qq).prefetch_related("user")
    if qq_link is None:
        return None

    user = qq_link.user

    default_acc = await UserAccount.get_or_none(user=user, platform=LXNS_PLATFORM, is_default=True)
    if default_acc is None:
        lxns_accounts = await UserAccount.filter(user=user, platform=LXNS_PLATFORM).order_by("-id")
        if not lxns_accounts:
            return None
        default_acc = lxns_accounts[0]

    return await GameProfile.get_or_none(account=default_acc).select_related("account")


async def set_default_lxns_account_for_qq(*, qq: str, lxns_account_key: str) -> None:
    qq_link = await UserAccount.get_or_none(platform=QQ_PLATFORM, account_key=qq).prefetch_related("user")
    if qq_link is None:
        return

    user = qq_link.user
    lxns_acc = await UserAccount.get_or_none(user=user, platform=LXNS_PLATFORM, account_key=lxns_account_key)
    if lxns_acc is None:
        return

    await UserAccount.filter(user=user, platform=LXNS_PLATFORM, is_default=True).update(is_default=False)
    lxns_acc.is_default = True
    await lxns_acc.save()
