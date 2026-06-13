from __future__ import annotations

import traceback
from dataclasses import dataclass
from typing import Literal

from ..account_store import TortoiseAccountStore
from ..binding.schemas import LxnsBindRequest, LxnsUniqueCodeCredential
from src.chiffon_data.integrations.lxns.binding import bind_upsert


@dataclass(frozen=True)
class BindResult:
    status: Literal["bound", "error"]
    message: str
    lxns_account_key: str = ""


async def bind_by_friend_code(*, qq: str, friend_code: str) -> BindResult:
    """将 QQ 用户绑定到 LXNS（friend_code/unique_code 方式）。

    只影响 UserAccount / GameProfile：
    - 确保 QQ 的 UserAccount 存在
    - upsert 一个 lxns UserAccount（platform=lxns）
    - 关联/更新 GameProfile（仅写 maimai_friend_code，name 由后续刷新填充）
    """

    try:
        store = TortoiseAccountStore()
        req = LxnsBindRequest(qq=qq, credential=LxnsUniqueCodeCredential(unique_code=friend_code))
        result = await bind_upsert(req, store)
        await store.upsert_game_profile(
            account_key=result.account_key,
            maimai_friend_code=friend_code,
        )

        return BindResult(
            status="bound",
            message="\n绑定成功！现在可以使用所有功能了~",
            lxns_account_key=result.account_key,
        )
    except Exception as e:
        traceback.print_exc()
        return BindResult(
            status="error",
            message=f"\n绑定过程中出现错误，请稍后重试。\n错误信息如下：{e}",
        )
