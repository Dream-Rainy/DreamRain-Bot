from __future__ import annotations

import traceback
from dataclasses import dataclass
from typing import Literal

from ..account_store import TortoiseAccountStore


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
        store = TortoiseAccountStore()
        if not await store.has_lxns_account(qq):
            return UnbindResult(status="not_bound", message="未找到该用户")

        deleted = await store.delete_lxns_accounts(qq)
        if deleted <= 0:
            return UnbindResult(status="not_bound", message="未绑定")

        return UnbindResult(status="unbound", message="解绑成功")
    except Exception as e:
        traceback.print_exc()
        return UnbindResult(status="error", message=f"解绑过程中出现错误：{e}")
