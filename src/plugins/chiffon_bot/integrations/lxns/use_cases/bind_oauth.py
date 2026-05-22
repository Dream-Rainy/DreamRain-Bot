from __future__ import annotations

import traceback
from dataclasses import dataclass
from typing import Literal

from ....infra.db.models import GameProfile, UserAccount
from ....infra.http import http_client
from ..binding.schemas import LxnsBindRequest, LxnsOAuthCredential
from ..binding.service import bind_upsert
from ..constants import user_chunithm_player_url, user_maimai_player_url
from ..oauth_client import oa_client


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


async def bind_by_oauth_code(*, qq: str, code: str, state: str) -> OAuthBindResult:
    try:
        wait_bind_user = oa_client.validate_wait_bind_user(state, user_id_hash=qq)
        token_data = await oa_client.get_token(code)

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
        result = await bind_upsert(req, account_name=maimai_name or chuni_name or f"lxns_user_{qq}")

        lxns_account = await UserAccount.get(platform="lxns", account_key=result.account_key)
        game_profile = await GameProfile.get_or_none(account=lxns_account)
        if game_profile is None:
            game_profile = await GameProfile.create(account=lxns_account, platform="lxns")

        if maimai_name:
            game_profile.maimai_name = maimai_name
        if maimai_friend_code:
            game_profile.maimai_friend_code = maimai_friend_code
        if chuni_name:
            game_profile.chunithm_name = chuni_name
        if chuni_friend_code:
            game_profile.chunithm_friend_code = chuni_friend_code
        await game_profile.save()

        oa_client.remove_wait_bind_user(state)
        oa_client.mark_bind_result(
            state=state,
            user_id_hash=qq,
            status="bound",
            message="OAuth 绑定成功",
            account_key=result.account_key,
        )

        return OAuthBindResult(status="bound", message="OAuth 绑定成功", account_key=result.account_key)
    except Exception as e:
        traceback.print_exc()
        oa_client.mark_bind_result(
            state=state,
            user_id_hash=qq,
            status="error",
            message=str(e),
        )
        return OAuthBindResult(status="error", message=f"OAuth 绑定过程中出现错误：{e}")