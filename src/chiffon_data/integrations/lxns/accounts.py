"""Account storage protocol for LXNS binding flows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class StoredLxnsAccount:
    user_id: int
    qq: str
    account_key: str
    account_name: str
    schema_version: int = 1
    is_default: bool = False


@dataclass(frozen=True)
class StoredGameProfile:
    account_key: str
    account_name: str
    maimai_name: str = ""
    maimai_friend_code: str = ""
    chunithm_name: str = ""
    chunithm_friend_code: str = ""


class AccountStore(Protocol):
    async def ensure_user_by_qq(self, qq: str) -> int:
        """Ensure a local user exists for QQ and return its user id."""

    async def upsert_lxns_account(
        self,
        *,
        qq: str,
        account_key: str,
        account_json: dict[str, Any],
        account_name: str,
    ) -> StoredLxnsAccount:
        """Create or update a LXNS account linked to the QQ user."""

    async def has_lxns_account(self, qq: str) -> bool:
        """Return whether the QQ user already has any LXNS account."""

    async def set_default_lxns_account(self, *, qq: str, account_key: str) -> None:
        """Mark one LXNS account as default for the QQ user."""

    async def get_default_game_profile(self, qq: str) -> StoredGameProfile | None:
        """Return the default LXNS game profile for the QQ user."""

    async def upsert_game_profile(
        self,
        *,
        account_key: str,
        maimai_name: str | None = None,
        maimai_friend_code: str | None = None,
        chunithm_name: str | None = None,
        chunithm_friend_code: str | None = None,
    ) -> StoredGameProfile:
        """Create or update the game profile attached to a LXNS account."""

    async def delete_lxns_accounts(self, qq: str) -> int:
        """Delete all LXNS accounts for the QQ user and return the count."""


__all__ = ["AccountStore", "StoredGameProfile", "StoredLxnsAccount"]
