from __future__ import annotations

from typing import Any

import pytest

from arcade_helper.integrations.lxns.accounts import StoredGameProfile, StoredLxnsAccount
from arcade_helper.integrations.lxns.binding import (
    LxnsBindRequest,
    LxnsUniqueCodeCredential,
    bind_upsert,
    build_account_key,
)


class FakeAccountStore:
    def __init__(self) -> None:
        self.saved: dict[str, Any] = {}

    async def ensure_user_by_qq(self, qq: str) -> int:
        return 1

    async def upsert_lxns_account(
        self,
        *,
        qq: str,
        account_key: str,
        account_json: dict[str, Any],
        account_name: str,
    ) -> StoredLxnsAccount:
        self.saved = {
            "qq": qq,
            "account_key": account_key,
            "account_json": account_json,
            "account_name": account_name,
        }
        return StoredLxnsAccount(
            user_id=1,
            qq=qq,
            account_key=account_key,
            account_name=account_name,
            schema_version=1,
            is_default=True,
        )

    async def has_lxns_account(self, qq: str) -> bool:
        return False

    async def set_default_lxns_account(self, *, qq: str, account_key: str) -> None:
        self.saved["default"] = (qq, account_key)

    async def get_default_game_profile(self, qq: str) -> StoredGameProfile | None:
        return None

    async def upsert_game_profile(self, **kwargs: Any) -> StoredGameProfile:
        return StoredGameProfile(account_key=str(kwargs["account_key"]), account_name="")

    async def delete_lxns_accounts(self, qq: str) -> int:
        return 0


@pytest.mark.asyncio
async def test_lxns_bind_upsert_uses_account_store_without_db():
    req = LxnsBindRequest(
        qq="123456",
        credential=LxnsUniqueCodeCredential(unique_code="1000000000"),
    )
    store = FakeAccountStore()

    result = await bind_upsert(req, store, account_name="Mai Player")

    assert result.user_id == 1
    assert result.qq == "123456"
    assert result.account_key == build_account_key(req)
    assert result.account_name == "Mai Player"
    assert store.saved["account_json"]["unique_code"] == "1000000000"
