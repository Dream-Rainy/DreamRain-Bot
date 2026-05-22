from __future__ import annotations

from datetime import datetime
from hashlib import sha256

from ....infra.db.models import User, UserAccount

from .schemas import (
    IdentityProvider,
    LxnsAccountJsonV1,
    LxnsAccountKey,
    LxnsAccountKeyType,
    LxnsApiKeyCredential,
    LxnsBindRequest,
    LxnsBindResult,
    LxnsOAuthCredential,
    LxnsProvider,
    LxnsUniqueCodeCredential,
)

def _hash_api_key(raw: str) -> str:
    return sha256(raw.encode("utf-8")).hexdigest()


def build_account_key(req: LxnsBindRequest) -> str:
    cred = req.credential

    if isinstance(cred, LxnsUniqueCodeCredential):
        return LxnsAccountKey(type=LxnsAccountKeyType.unique_code, value=cred.unique_code).to_string()

    if isinstance(cred, LxnsOAuthCredential):
        return LxnsAccountKey(type=LxnsAccountKeyType.oa, value="oauth").to_string()

    if isinstance(cred, LxnsApiKeyCredential):
        h = _hash_api_key(cred.api_key.get_secret_value())
        return LxnsAccountKey(type=LxnsAccountKeyType.api_key, value=f"sha256:{h}").to_string()

    raise TypeError(f"Unsupported credential: {type(cred)!r}")


def build_account_json(req: LxnsBindRequest) -> LxnsAccountJsonV1:
    cred = req.credential
    now = datetime.utcnow()

    if isinstance(cred, LxnsUniqueCodeCredential):
        return LxnsAccountJsonV1(method=cred.method, unique_code=cred.unique_code, last_updated_at=now)

    if isinstance(cred, LxnsApiKeyCredential):
        return LxnsAccountJsonV1(method=cred.method, api_key=cred.api_key, last_updated_at=now)

    if isinstance(cred, LxnsOAuthCredential):
        return LxnsAccountJsonV1(
            method=cred.method,
            oauth2_access_token=cred.access_token,
            oauth2_refresh_token=cred.refresh_token,
            oauth2_token_expiry=cred.token_expiry,
            oauth2_refresh_expiry=cred.refresh_expiry,
            last_updated_at=now,
        )

    raise TypeError(f"Unsupported credential: {type(cred)!r}")

async def bind_upsert(req: LxnsBindRequest, account_name: str | None = None) -> LxnsBindResult:
    qq_link = await UserAccount.get_or_none(platform=IdentityProvider.qq.value, account_key=req.qq).prefetch_related(
        "user"
    )
    if qq_link is None:
        user = await User.create(profile_json={})
        await UserAccount.create(
            user=user,
            platform=IdentityProvider.qq.value,
            account_key=req.qq,
            account_name=f"QQ_{req.qq}",
            schema_version=1,
            account_json={"qq": req.qq},
        )
    else:
        user = qq_link.user

    account_key = build_account_key(req)
    account_json = build_account_json(req)

    has_default_lxns = await UserAccount.get_or_none(user=user, platform=LxnsProvider.lxns.value, is_default=True)

    # 如果没有提供 account_name，使用默认值
    if account_name is None:
        account_name = f"lxns_user_{req.qq}"

    obj = await UserAccount.get_or_none(platform=LxnsProvider.lxns.value, account_key=account_key)
    if obj is None:
        obj = await UserAccount.create(
            user=user,
            platform=LxnsProvider.lxns.value,
            account_key=account_key,
            account_name=account_name,
            is_default=has_default_lxns is None,
            schema_version=1,
            account_json=account_json.model_dump(mode="json"),
        )
    else:
        obj.user = user
        obj.schema_version = 1
        obj.account_json = account_json.model_dump(mode="json")
        # 总是更新 account_name，确保不为 None
        obj.account_name = account_name
        await obj.save()

    return LxnsBindResult(
        user_id=user.id,
        qq=req.qq,
        platform=LxnsProvider.lxns,
        account_key=account_key,
        account_name=obj.account_name,
        schema_version=obj.schema_version,
        stored_at=datetime.utcnow(),
    )
