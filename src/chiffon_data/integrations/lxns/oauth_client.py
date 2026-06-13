from __future__ import annotations

import base64
import secrets
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from hashlib import sha256
from typing import Any
from urllib.parse import urlencode

from .constants import oauth_authorize_url, oauth_token_url

HttpPostJson = Callable[..., Awaitable[Any]]


class OauthClient:
    def __init__(
        self,
        *,
        http_post_json: HttpPostJson,
        client_id: str,
        client_secret: str,
        base_url: str = "https://maimai.lxns.net",
        redirect_uri: str = "",
        scope: str = "",
        state_ttl_seconds: int = 600,
        relay_url: str = "",
    ):
        self.http_post_json = http_post_json
        self.client_id = client_id
        self.client_secret = client_secret
        self.base_url = base_url
        self.redirect_uri = redirect_uri
        self.scope = scope
        self.state_ttl_seconds = state_ttl_seconds
        self.wait_bind_user: dict[str, dict[str, Any]] = {}
        self.bind_results_by_state: dict[str, dict[str, Any]] = {}
        self.bind_results_by_user: dict[str, dict[str, Any]] = {}

        # Relay 模式的 redirect_uri 从 relay_url 自动推导
        if not self.redirect_uri and relay_url:
            self.redirect_uri = f"{relay_url.rstrip('/')}/callback"
            self._using_relay = True
        else:
            self._using_relay = False

    def _now(self) -> datetime:
        return datetime.utcnow()

    def _is_expired(self, created_at: datetime) -> bool:
        return self._now() - created_at > timedelta(seconds=self.state_ttl_seconds)

    def cleanup_wait_bind_user(self) -> None:
        expired_states = [state for state, data in self.wait_bind_user.items() if self._is_expired(data["created_at"])]
        for state in expired_states:
            del self.wait_bind_user[state]

    def generate_code_verifier(self) -> str:
        return secrets.token_urlsafe(64)

    def generate_code_challenge(self, verifier: str) -> str:
        digest = sha256(verifier.encode("utf-8")).digest()
        return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("utf-8")

    def add_wait_bind_user(self, user_id_hash: str) -> str:
        self.cleanup_wait_bind_user()

        state = secrets.token_urlsafe(24)
        self.wait_bind_user[state] = {
            "code": "",
            "state": state,
            "user_id_hash": user_id_hash,
            "created_at": self._now(),
        }
        return state

    def remove_wait_bind_user(self, user_id_hash: str):
        states_to_remove = [
            state
            for state, data in self.wait_bind_user.items()
            if state == user_id_hash or data.get("user_id_hash") == user_id_hash
        ]
        for state in states_to_remove:
            del self.wait_bind_user[state]

    def get_wait_bind_user(self, state: str) -> dict[str, Any] | None:
        self.cleanup_wait_bind_user()
        return self.wait_bind_user.get(state)

    def validate_wait_bind_user(self, state: str, *, user_id_hash: str | None = None) -> dict[str, Any]:
        wait_bind_user = self.get_wait_bind_user(state)
        if wait_bind_user is None:
            raise ValueError("绑定状态不存在或已过期，请重新获取授权链接")

        if user_id_hash is not None and wait_bind_user.get("user_id_hash") != user_id_hash:
            raise ValueError("绑定状态不匹配，请重新获取授权链接")

        return wait_bind_user

    def mark_bind_result(
        self,
        *,
        state: str,
        user_id_hash: str,
        status: str,
        message: str,
        account_key: str | None = None,
    ) -> None:
        result = {
            "state": state,
            "user_id_hash": user_id_hash,
            "status": status,
            "message": message,
            "account_key": account_key,
            "created_at": self._now(),
        }
        self.bind_results_by_state[state] = result
        self.bind_results_by_user[user_id_hash] = result

    def get_bind_result_by_user(self, user_id_hash: str) -> dict[str, Any] | None:
        return self.bind_results_by_user.get(user_id_hash)

    def get_bind_result_by_state(self, state: str) -> dict[str, Any] | None:
        return self.bind_results_by_state.get(state)

    def get_bind_uri(
        self,
        state: str,
        *,
        code_challenge: str | None = None,
        code_challenge_method: str = "S256",
    ) -> str:
        if not self.redirect_uri:
            return "该绑定方式暂不可用"

        query = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "state": state,
        }
        query["scope"] = self.scope or "read_player"
        if code_challenge:
            query["code_challenge"] = code_challenge
            query["code_challenge_method"] = code_challenge_method

        bind_uri = f"{oauth_authorize_url(base_url=self.base_url)}?{urlencode(query)}"
        return f"请在浏览器中打开以下链接进行绑定：\n{bind_uri}\n"

    def _extract_payload(self, result: Any) -> dict[str, Any]:
        if isinstance(result, dict):
            data = result.get("data")
            if isinstance(data, dict):
                return data
            return result
        return {}

    def _build_token_result(self, payload: dict[str, Any]) -> dict[str, Any]:
        access_token = payload.get("access_token")
        refresh_token = payload.get("refresh_token")
        token_type = payload.get("token_type", "Bearer")
        expires_in = payload.get("expires_in", 900)
        scope = payload.get("scope", self.scope or "read_player")

        if not access_token:
            raise ValueError("获取访问令牌失败，请检查授权码是否正确或是否已过期")
        if not refresh_token:
            raise ValueError("获取刷新令牌失败，请稍后重试")

        expires_in_int = int(expires_in)
        now = self._now()
        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": token_type,
            "expires_in": expires_in_int,
            "scope": scope,
            "token_expiry": now + timedelta(seconds=expires_in_int),
            "refresh_expiry": now + timedelta(days=30),
        }

    async def get_token(self, auth_code: str, *, code_verifier: str | None = None) -> dict[str, Any]:
        if not auth_code:
            raise ValueError("授权码不能为空")

        if not self.redirect_uri:
            raise ValueError("该绑定方式暂不可用")

        uri = oauth_token_url(base_url=self.base_url)
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "authorization_code",
            "code": auth_code,
            "redirect_uri": self.redirect_uri,
        }
        if code_verifier:
            data["code_verifier"] = code_verifier

        try:
            result = await self.http_post_json(uri, json_data=data)
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"获取访问令牌失败：{exc}") from exc

        payload = self._extract_payload(result)
        return self._build_token_result(payload)

    async def refresh_token(self, refresh_token: str, *, code_verifier: str | None = None) -> dict[str, Any]:
        if not refresh_token:
            raise ValueError("刷新令牌不能为空")

        uri = oauth_token_url(base_url=self.base_url)
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }
        if code_verifier:
            data["code_verifier"] = code_verifier

        try:
            result = await self.http_post_json(uri, json_data=data)
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"刷新访问令牌失败：{exc}") from exc

        payload = self._extract_payload(result)
        return self._build_token_result(payload)

__all__ = ["OauthClient"]
