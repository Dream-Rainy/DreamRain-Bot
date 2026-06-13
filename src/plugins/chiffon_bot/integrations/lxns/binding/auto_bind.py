"""自动绑定服务：通过 QQ 号自动从 LXNS API 获取用户信息并绑定。"""

from __future__ import annotations

import traceback
from dataclasses import dataclass
from typing import Literal

from nonebot.log import logger

from ....infra.http.client import HttpClient
from ..account_store import TortoiseAccountStore
from ..constants import maimai_player_by_qq_url, maimai_player_url
from .schemas import LxnsBindRequest, LxnsUniqueCodeCredential
from src.chiffon_data.integrations.lxns.binding import bind_upsert


_client = HttpClient()


@dataclass(frozen=True)
class AutoBindResult:
    status: Literal["bound", "already_bound", "not_found", "error"]
    message: str
    lxns_account_key: str = ""


async def check_if_bound(qq: str) -> bool:
    """检查用户是否已经绑定了 LXNS 账号。"""
    return await TortoiseAccountStore().has_lxns_account(qq)


async def auto_bind_by_qq(qq: str, headers: dict) -> AutoBindResult:
    """通过 QQ 号自动绑定用户。
    
    流程：
    1. 检查是否已绑定
    2. 通过 /api/v0/maimai/player/qq/{qq} 获取 friend_code
    3. 通过 /api/v0/maimai/player/{friend_code} 获取用户名
    4. 使用 unique_code 方式绑定（friend_code 即为 unique_code）
    5. 更新 GameProfile
    """
    
    logger.info(f"开始为 QQ {qq} 进行自动绑定")
    
    # 检查是否已绑定
    if await check_if_bound(qq):
        logger.info(f"QQ {qq} 已经绑定，跳过")
        return AutoBindResult(
            status="already_bound",
            message="您已经绑定过了~",
        )
    
    try:
        # 1. 通过 QQ 号获取 friend_code
        qq_url = maimai_player_by_qq_url(qq)
        logger.debug(f"正在从 {qq_url} 获取 friend_code")
        qq_response = await _client.get_json(qq_url, headers=headers)
        
        if not qq_response.get("success"):
            logger.warning(f"QQ {qq} 在 LXNS 中未找到: {qq_response}")
            return AutoBindResult(
                status="not_found",
                message="在 LXNS 中未找到您的信息，请确保您已在 LXNS 网站上注册并绑定了 QQ 号。",
            )
        
        qq_data = qq_response.get("data", {})
        friend_code = str(qq_data.get("friend_code", ""))
        logger.info(f"QQ {qq} 的 friend_code: {friend_code}")
        
        if not friend_code:
            logger.error(f"QQ {qq} 返回的数据缺少 friend_code: {qq_data}")
            return AutoBindResult(
                status="error",
                message="从 LXNS 获取的数据不完整（缺少 friend_code），请稍后再试。",
            )
        
        # 2. 通过 friend_code 获取用户详细信息（包括用户名）
        player_url_str = maimai_player_url(friend_code)
        logger.debug(f"正在从 {player_url_str} 获取玩家详细信息")
        player_response = await _client.get_json(player_url_str, headers=headers)
        
        if not player_response.get("success"):
            logger.error(f"无法获取 friend_code {friend_code} 的玩家详细信息: {player_response}")
            return AutoBindResult(
                status="error",
                message="无法获取玩家详细信息，请稍后再试。",
            )
        
        player_data = player_response.get("data", {})
        player_name = player_data.get("name", "")
        logger.info(f"获取到玩家名: {player_name}")
        
        # 3. 使用 unique_code 方式绑定（friend_code 即为 unique_code）
        req = LxnsBindRequest(
            qq=qq,
            credential=LxnsUniqueCodeCredential(unique_code=friend_code)
        )
        
        logger.debug(f"开始执行绑定操作: qq={qq}, friend_code={friend_code}, player_name={player_name}")
        # 执行绑定，使用从 API 获取的玩家名称作为 account_name
        store = TortoiseAccountStore()
        result = await bind_upsert(req, store, account_name=player_name if player_name else None)
        logger.info(f"绑定操作完成: account_key={result.account_key}")
        
        await store.upsert_game_profile(
            account_key=result.account_key,
            maimai_name=player_name,
            maimai_friend_code=friend_code,
        )
        logger.info(f"GameProfile 已更新: maimai_name={player_name}, friend_code={friend_code}")
        
        return AutoBindResult(
            status="bound",
            message=f"自动绑定成功！欢迎 {player_name}~",
            lxns_account_key=result.account_key,
        )
        
    except Exception as e:
        traceback.print_exc()
        logger.exception(f"QQ {qq} 自动绑定过程中发生异常")
        return AutoBindResult(
            status="error",
            message=f"自动绑定失败: {str(e)}",
        )


async def ensure_user_bound(qq: str, headers: dict) -> AutoBindResult:
    """确保用户已绑定。如果未绑定，则自动进行绑定。
    
    返回：
        AutoBindResult: 绑定结果，包含状态和消息
    """
    if await check_if_bound(qq):
        return AutoBindResult(
            status="already_bound",
            message="用户已绑定",
        )
    
    return await auto_bind_by_qq(qq, headers)


__all__ = ["auto_bind_by_qq", "check_if_bound", "ensure_user_bound", "AutoBindResult"]
