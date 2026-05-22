from __future__ import annotations

import traceback
from dataclasses import dataclass
from typing import Literal

from ....infra.db.models import GameProfile, QQ_PLATFORM, UserAccount
from ..session import LXNS_PLATFORM


@dataclass(frozen=True)
class UnbindResult:
    status: Literal["unbound", "not_bound", "error"]
    message: str


async def unbind_lxns_for_qq(*, qq: str) -> UnbindResult:
    """解绑 QQ 对应的 LXNS 账号。

    约束：只影响 UserAccount（及其关联的 GameProfile），不删除 User。

    当前策略：
    - 定位 QQ 的 UserAccount -> user
    - 删除该 user 下所有 platform=lxns 的 UserAccount（级联删除其 GameProfile）
    """

    try:
        qq_link = await UserAccount.get_or_none(platform=QQ_PLATFORM, account_key=qq).prefetch_related("user")
        if qq_link is None:
            return UnbindResult(status="not_bound", message="未找到该用户")

        user = qq_link.user
        lxns_accounts = await UserAccount.filter(user=user, platform=LXNS_PLATFORM)
        if not lxns_accounts:
            return UnbindResult(status="not_bound", message="未绑定")

        # 显式删除关联的 GameProfile（保险起见），再删账号
        for acc in lxns_accounts:
            gp = await GameProfile.get_or_none(account=acc)
            if gp is not None:
                await gp.delete()
            await acc.delete()

        return UnbindResult(status="unbound", message="解绑成功")
    except Exception as e:
        traceback.print_exc()
        return UnbindResult(status="error", message=f"解绑过程中出现错误：{e}")
