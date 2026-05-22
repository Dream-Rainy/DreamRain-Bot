from __future__ import annotations

from datetime import datetime, timedelta

from .schemas import LxnsBindRequest
from .service import bind_upsert


async def example_bind_via_oa(user_id: str) -> None:
    req = LxnsBindRequest.model_validate(
        {
            "qq": user_id,
            "credential": {
                "method": "oa",
                "access_token": "access-token-here",
                "refresh_token": "refresh-token-here",
                "token_expiry": (datetime.utcnow() + timedelta(minutes=15)).isoformat(),
                "refresh_expiry": (datetime.utcnow() + timedelta(days=30)).isoformat(),
            },
        }
    )
    result = await bind_upsert(req)
    print(result.model_dump())


async def example_parse_three_methods() -> None:
    LxnsBindRequest.model_validate({"qq": "123", "credential": {"method": "unique_code", "unique_code": "ABCD1234"}})
    LxnsBindRequest.model_validate({"qq": "123", "credential": {"method": "api_key", "api_key": "my-secret"}})
    LxnsBindRequest.model_validate(
        {
            "qq": "123",
            "credential": {
                "method": "oa",
                "access_token": "a",
                "refresh_token": "b",
                "token_expiry": datetime.utcnow().isoformat(),
            },
        }
    )
