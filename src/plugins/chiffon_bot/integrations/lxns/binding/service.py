"""Bot-side adapter for LXNS binding persistence."""

from __future__ import annotations

from src.chiffon_data.integrations.lxns.binding import (
    bind_upsert as _bind_upsert,
    build_account_json,
    build_account_key,
)

from ..account_store import TortoiseAccountStore
from .schemas import LxnsBindRequest, LxnsBindResult


async def bind_upsert(req: LxnsBindRequest, account_name: str | None = None) -> LxnsBindResult:
    return await _bind_upsert(req, TortoiseAccountStore(), account_name=account_name)


__all__ = ["bind_upsert", "build_account_json", "build_account_key"]
