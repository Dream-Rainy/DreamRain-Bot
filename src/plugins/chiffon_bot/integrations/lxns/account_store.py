"""Tortoise-backed AccountStore implementation for LXNS integrations."""

from __future__ import annotations

from typing import Any

from src.chiffon_data.integrations.lxns.accounts import StoredGameProfile, StoredLxnsAccount

from ...infra.db.models import GameProfile, QQ_PLATFORM, User, UserAccount, ensure_user_by_qq

LXNS_PLATFORM = "lxns"


class TortoiseAccountStore:
    async def ensure_user_by_qq(self, qq: str) -> int:
        user = await ensure_user_by_qq(qq)
        return int(user.id)

    async def _get_user_by_qq(self, qq: str) -> User | None:
        qq_link = await UserAccount.get_or_none(platform=QQ_PLATFORM, account_key=qq).prefetch_related("user")
        return qq_link.user if qq_link else None

    async def upsert_lxns_account(
        self,
        *,
        qq: str,
        account_key: str,
        account_json: dict[str, Any],
        account_name: str,
    ) -> StoredLxnsAccount:
        await self.ensure_user_by_qq(qq)
        user = await self._get_user_by_qq(qq)
        if user is None:
            raise ValueError(f"无法创建 QQ 用户: {qq}")

        has_default_lxns = await UserAccount.get_or_none(
            user=user,
            platform=LXNS_PLATFORM,
            is_default=True,
        )

        obj = await UserAccount.get_or_none(platform=LXNS_PLATFORM, account_key=account_key)
        if obj is None:
            obj = await UserAccount.create(
                user=user,
                platform=LXNS_PLATFORM,
                account_key=account_key,
                account_name=account_name,
                is_default=has_default_lxns is None,
                schema_version=1,
                account_json=account_json,
            )
        else:
            obj.user = user
            obj.schema_version = 1
            obj.account_json = account_json
            obj.account_name = account_name
            if has_default_lxns is None:
                obj.is_default = True
            await obj.save()

        return StoredLxnsAccount(
            user_id=int(user.id),
            qq=qq,
            account_key=str(obj.account_key),
            account_name=str(obj.account_name or ""),
            schema_version=int(obj.schema_version),
            is_default=bool(obj.is_default),
        )

    async def has_lxns_account(self, qq: str) -> bool:
        user = await self._get_user_by_qq(qq)
        if user is None:
            return False
        return await UserAccount.filter(user=user, platform=LXNS_PLATFORM).exists()

    async def set_default_lxns_account(self, *, qq: str, account_key: str) -> None:
        user = await self._get_user_by_qq(qq)
        if user is None:
            return

        lxns_acc = await UserAccount.get_or_none(user=user, platform=LXNS_PLATFORM, account_key=account_key)
        if lxns_acc is None:
            return

        await UserAccount.filter(user=user, platform=LXNS_PLATFORM, is_default=True).update(is_default=False)
        lxns_acc.is_default = True
        await lxns_acc.save()

    async def _default_lxns_account_for_qq(self, qq: str) -> UserAccount | None:
        user = await self._get_user_by_qq(qq)
        if user is None:
            return None

        default_acc = await UserAccount.get_or_none(user=user, platform=LXNS_PLATFORM, is_default=True)
        if default_acc is not None:
            return default_acc

        lxns_accounts = await UserAccount.filter(user=user, platform=LXNS_PLATFORM).order_by("-id")
        return lxns_accounts[0] if lxns_accounts else None

    async def get_default_game_profile(self, qq: str) -> StoredGameProfile | None:
        default_acc = await self._default_lxns_account_for_qq(qq)
        if default_acc is None:
            return None

        gp = await GameProfile.get_or_none(account=default_acc)
        if gp is None:
            return StoredGameProfile(
                account_key=str(default_acc.account_key),
                account_name=str(default_acc.account_name or ""),
            )
        return _profile_record(default_acc, gp)

    async def upsert_game_profile(
        self,
        *,
        account_key: str,
        maimai_name: str | None = None,
        maimai_friend_code: str | None = None,
        chunithm_name: str | None = None,
        chunithm_friend_code: str | None = None,
    ) -> StoredGameProfile:
        lxns_account = await UserAccount.get(platform=LXNS_PLATFORM, account_key=account_key)
        gp = await GameProfile.get_or_none(account=lxns_account)
        if gp is None:
            gp = await GameProfile.create(account=lxns_account, platform=LXNS_PLATFORM)

        if maimai_name is not None:
            gp.maimai_name = maimai_name
        if maimai_friend_code is not None:
            gp.maimai_friend_code = maimai_friend_code
        if chunithm_name is not None:
            gp.chunithm_name = chunithm_name
        if chunithm_friend_code is not None:
            gp.chunithm_friend_code = chunithm_friend_code
        await gp.save()
        return _profile_record(lxns_account, gp)

    async def delete_lxns_accounts(self, qq: str) -> int:
        user = await self._get_user_by_qq(qq)
        if user is None:
            return 0

        lxns_accounts = await UserAccount.filter(user=user, platform=LXNS_PLATFORM)
        deleted = 0
        for acc in lxns_accounts:
            gp = await GameProfile.get_or_none(account=acc)
            if gp is not None:
                await gp.delete()
            await acc.delete()
            deleted += 1
        return deleted


def _profile_record(account: UserAccount, profile: GameProfile) -> StoredGameProfile:
    return StoredGameProfile(
        account_key=str(account.account_key),
        account_name=str(account.account_name or ""),
        maimai_name=str(profile.maimai_name or ""),
        maimai_friend_code=str(profile.maimai_friend_code or ""),
        chunithm_name=str(profile.chunithm_name or ""),
        chunithm_friend_code=str(profile.chunithm_friend_code or ""),
    )


__all__ = ["TortoiseAccountStore"]
