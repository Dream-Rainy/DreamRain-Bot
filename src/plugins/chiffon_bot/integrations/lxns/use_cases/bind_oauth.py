from __future__ import annotations

import traceback
from dataclasses import dataclass
from typing import Literal

from ....infra.http import http_client
from ..account_store import TortoiseAccountStore
from ..binding.schemas import LxnsBindRequest, LxnsOAuthCredential
from ..constants import user_chunithm_player_url, user_maimai_player_url
from ..oauth_client import oa_client
from src.chiffon_data.integrations.lxns.binding import bind_upsert


@dataclass(frozen=True)
class OAuthBindResult:
    status: Literal["bound", "error"]
    message: str
    account_key: str = ""


def _extract_name_and_code(response: dict) -> tuple[str, str]:
    data = response.get("data") if isinstance(response, dict) else None
    payload = data if isinstance(data, dict) else response
    name = payload.get("name", "") if isinstance(payload, dict) else ""
    friend_code = payload.get("friend_code", "") if isinstance(payload, dict) else ""
    return name or "", friend_code or ""


async def _do_bind(*, qq: str, token_data: dict) -> OAuthBindResult:
    access_token = token_data["access_token"]
    refresh_token = token_data["refresh_token"]
    token_expiry = token_data["token_expiry"]
    refresh_expiry = token_data["refresh_expiry"]

    player_headers = {"Authorization": f"Bearer {access_token}"}
    maimai_response = await http_client.get_json(user_maimai_player_url(), headers=player_headers)
    chuni_response = await http_client.get_json(user_chunithm_player_url(), headers=player_headers)

    maimai_name, maimai_friend_code = _extract_name_and_code(maimai_response)
    chuni_name, chuni_friend_code = _extract_name_and_code(chuni_response)

    credential = LxnsOAuthCredential(
        access_token=access_token,
        refresh_token=refresh_token,
        token_expiry=token_expiry,
        refresh_expiry=refresh_expiry,
    )
    req = LxnsBindRequest(qq=qq, credential=credential)
    store = TortoiseAccountStore()
    result = await bind_upsert(req, store, account_name=maimai_name or chuni_name or f"lxns_user_{qq}")
    await store.upsert_game_profile(
        account_key=result.account_key,
        maimai_name=maimai_name if maimai_name else None,
        maimai_friend_code=maimai_friend_code if maimai_friend_code else None,
        chunithm_name=chuni_name if chuni_name else None,
        chunithm_friend_code=chuni_friend_code if chuni_friend_code else None,
    )

    return OAuthBindResult(status="bound", message="OAuth 绑定成功", account_key=result.account_key)


async def bind_by_oauth_code(*, qq: str, code: str, state: str) -> OAuthBindResult:
    """通过 OAuth 回调完成绑定（方案 A：校验 state）。"""
    try:
        oa_client.validate_wait_bind_user(state, user_id_hash=qq)
        token_data = await oa_client.get_token(code)
        result = await _do_bind(qq=qq, token_data=token_data)

        oa_client.remove_wait_bind_user(state)
        oa_client.mark_bind_result(
            state=state,
            user_id_hash=qq,
            status="bound",
            message="OAuth 绑定成功",
            account_key=result.account_key,
        )
        return result
    except Exception as e:
        traceback.print_exc()
        oa_client.mark_bind_result(
            state=state,
            user_id_hash=qq,
            status="error",
            message=str(e),
        )
        return OAuthBindResult(status="error", message=f"OAuth 绑定过程中出现错误：{e}")
