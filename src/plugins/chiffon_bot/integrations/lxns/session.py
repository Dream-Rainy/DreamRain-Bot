import functools
import traceback
from datetime import datetime

from .oauth_client import oa_client
from ...infra.db.models import GameProfile, QQ_PLATFORM, User, UserAccount, ensure_user_by_qq, get_user_by_qq
from ...infra.http import http_client
from .constants import (
    chunithm_player_by_qq_url,
    maimai_player_by_qq_url,
    user_chunithm_player_url,
    user_maimai_player_url,
)


LXNS_PLATFORM = "lxns"


async def _ensure_qq_account(user: User, qq: str) -> UserAccount:
    obj = await UserAccount.get_or_none(platform=QQ_PLATFORM, account_key=qq)
    if obj is None:
        obj = await UserAccount.create(
            user=user,
            platform=QQ_PLATFORM,
            account_key=qq,
            schema_version=1,
            account_json={"qq": qq},
        )
    return obj


async def _get_or_create_lxns_account(user: User) -> UserAccount:
    obj = await UserAccount.get_or_none(user=user, platform=LXNS_PLATFORM, account_key="default")
    if obj is None:
        obj = await UserAccount.create(
            user=user,
            platform=LXNS_PLATFORM,
            account_key="default",
            schema_version=1,
            account_json={},
        )
    return obj


async def _get_or_create_game_profile(lxns_account: UserAccount) -> GameProfile:
    gp = await GameProfile.get_or_none(account=lxns_account)
    if gp is None:
        gp = await GameProfile.create(account=lxns_account, platform=LXNS_PLATFORM)
    return gp


def _get_oauth2(lxns_account: UserAccount) -> dict:
    return (lxns_account.account_json or {}).get("oauth2", {})


def _set_oauth2(lxns_account: UserAccount, oauth2: dict) -> None:
    account_json = dict(lxns_account.account_json or {})
    account_json["oauth2"] = oauth2
    lxns_account.account_json = account_json


def ensure_token_valid(method):
    @functools.wraps(method)
    async def wrapper(self, *args, **kwargs):
        now = datetime.now()

        oauth2 = _get_oauth2(self.lxns_account)
        token_expiry_raw = oauth2.get("token_expiry")
        token_expiry = None
        if token_expiry_raw:
            try:
                token_expiry = datetime.fromisoformat(token_expiry_raw)
            except Exception:
                traceback.print_exc()
                token_expiry = None

        if token_expiry is not None and token_expiry <= now:
            print("Access token 过期，正在刷新...")
            try:
                token_resp = await oa_client.refresh_token(oauth2.get("refresh_token", ""))
                access_token = token_resp["access_token"]
                refresh_token = token_resp["refresh_token"]
            except Exception as e:
                traceback.print_exc()
                print(f"刷新 access token 失败: {e}")
                raise ValueError(
                    "无法刷新 access token，可能是refresh token 已过期或无效，请重新绑定。"
                )

            oauth2["access_token"] = access_token
            oauth2["refresh_token"] = refresh_token
            oauth2["token_expiry"] = datetime.fromtimestamp(datetime.now().timestamp() + 900).isoformat()
            oauth2["refresh_expiry"] = datetime.fromtimestamp(
                datetime.now().timestamp() + 30 * 24 * 60 * 60
            ).isoformat()
            _set_oauth2(self.lxns_account, oauth2)
            await self.save()

        return await method(self, *args, **kwargs)

    return wrapper


class UserSession:
    """LXNS 平台用户会话。"""

    def __init__(self, qq: str, user: User, lxns_account: UserAccount):
        self.qq = qq
        self.user = user
        self.lxns_account = lxns_account

    @classmethod
    def from_user(cls, user: User):
        raise NotImplementedError("Use from_user_qq / from_user_id")

    @classmethod
    async def from_user_id(cls, user_id: str):
        user = await ensure_user_by_qq(user_id)
        lxns_account = await _get_or_create_lxns_account(user)
        return cls(qq=user_id, user=user, lxns_account=lxns_account)

    @classmethod
    async def from_user_qq(cls, dev_headers: dict[str, str], qq: str):
        user = await get_user_by_qq(qq)
        if user:
            lxns_account = await _get_or_create_lxns_account(user)
            return cls(qq=qq, user=user, lxns_account=lxns_account)

        get_info = False
        maimai_uri = maimai_player_by_qq_url(qq)
        chuni_uri = chunithm_player_by_qq_url(qq)
        maimai_response = await http_client.get_json(maimai_uri, headers=dev_headers)
        chuni_response = await http_client.get_json(chuni_uri, headers=dev_headers)

        user = await ensure_user_by_qq(qq)
        await _ensure_qq_account(user, qq)
        lxns_account = await _get_or_create_lxns_account(user)
        game_profile = await _get_or_create_game_profile(lxns_account)

        if maimai_response.get("code", 0) == 200:
            game_profile.maimai_name = maimai_response.get("data", {}).get("name", "")
            game_profile.maimai_friend_code = maimai_response.get("data", {}).get("friend_code", "")
            get_info = True

        if chuni_response.get("code", 0) == 200:
            game_profile.chunithm_name = chuni_response.get("data", {}).get("name", "")
            game_profile.chunithm_friend_code = chuni_response.get("data", {}).get("friend_code", "")
            get_info = True

        if not get_info:
            raise ValueError("无法获取用户信息，请检查QQ号是否绑定")

        await game_profile.save()
        return cls(qq=qq, user=user, lxns_account=lxns_account)

    async def save(self):
        assert self.user, "user must be set"
        await self.lxns_account.save()

    async def create_userinfo_via_oa(
        self, access_token: str, refresh_token: str
    ) -> tuple[str, str]:
        get_info = False
        player_headers = {"Authorization": f"Bearer {access_token}"}
        maimai_player_uri = user_maimai_player_url()
        chuni_play_uri = user_chunithm_player_url()

        maimai_response = await http_client.get_json(maimai_player_uri, headers=player_headers)
        chuni_response = await http_client.get_json(chuni_play_uri, headers=player_headers)

        if self.user is None:
            self.user = await ensure_user_by_qq(self.qq)
        await _ensure_qq_account(self.user, self.qq)
        self.lxns_account = await _get_or_create_lxns_account(self.user)
        game_profile = await _get_or_create_game_profile(self.lxns_account)

        if maimai_response.get("code", 0) == 200:
            game_profile.maimai_name = maimai_response.get("data", {}).get("name", "")
            game_profile.maimai_friend_code = maimai_response.get("data", {}).get("friend_code", "")
            get_info = True

        if chuni_response.get("code", 0) == 200:
            game_profile.chunithm_name = chuni_response.get("data", {}).get("name", "")
            game_profile.chunithm_friend_code = chuni_response.get("data", {}).get("friend_code", "")
            get_info = True

        if not get_info:
            raise ValueError("无法获取用户信息，请检查OAuth2.0令牌是否有效")

        oauth2 = _get_oauth2(self.lxns_account)
        oauth2["access_token"] = access_token
        oauth2["refresh_token"] = refresh_token
        oauth2["token_expiry"] = datetime.fromtimestamp(datetime.now().timestamp() + 900).isoformat()
        oauth2["refresh_expiry"] = datetime.fromtimestamp(
            datetime.now().timestamp() + 30 * 24 * 60 * 60
        ).isoformat()
        _set_oauth2(self.lxns_account, oauth2)

        await game_profile.save()
        await self.save()

        return game_profile.maimai_name or "", game_profile.chunithm_name or ""

    @ensure_token_valid
    async def refresh_userinfo_via_oa(self):
        oauth2 = _get_oauth2(self.lxns_account)
        if not oauth2.get("access_token") or not oauth2.get("refresh_token"):
            raise ValueError("用户未绑定OAuth2.0令牌，无法刷新信息")

        return await self.create_userinfo_via_oa(
            oauth2.get("access_token", ""), oauth2.get("refresh_token", "")
        )


__all__ = ["UserSession", "ensure_token_valid"]
