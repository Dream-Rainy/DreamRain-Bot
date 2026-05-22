from __future__ import annotations

import traceback
from dataclasses import dataclass
from typing import Literal

from ....infra.db.models import GameProfile, UserAccount, ensure_user_by_qq
from ..session import LXNS_PLATFORM
from ..binding.schemas import LxnsBindRequest, LxnsUniqueCodeCredential
from ..binding.service import bind_upsert
from .default_account import set_default_lxns_account_for_qq


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
        await ensure_user_by_qq(qq)
        req = LxnsBindRequest(qq=qq, credential=LxnsUniqueCodeCredential(unique_code=friend_code))
        result = await bind_upsert(req)

        lxns_account = await UserAccount.get(platform=LXNS_PLATFORM, account_key=result.account_key).prefetch_related("user")
        gp = await GameProfile.get_or_none(account=lxns_account)
        if gp is None:
            gp = await GameProfile.create(account=lxns_account, platform=LXNS_PLATFORM)

        gp.maimai_friend_code = friend_code
        await gp.save()

        has_default = await UserAccount.get_or_none(user=lxns_account.user, platform=LXNS_PLATFORM, is_default=True)
        if has_default is None:
            await set_default_lxns_account_for_qq(qq=qq, lxns_account_key=result.account_key)

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
