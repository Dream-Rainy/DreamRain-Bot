from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, Literal, Optional, Union

from pydantic import BaseModel, Field, SecretStr


class LxnsBindMethod(str, Enum):
    """LXNS 外部账号绑定方式。"""

    unique_code = "unique_code"
    api_key = "api_key"
    oa = "oa"


class LxnsProvider(str, Enum):
    """外部来源标识；用于落库 platform 字段。"""

    lxns = "lxns"


class IdentityProvider(str, Enum):
    """用于定位内部用户的账号来源（落库到 UserAccount.platform）。"""

    qq = "qq"


class LxnsUniqueCodeCredential(BaseModel):
    method: Literal[LxnsBindMethod.unique_code] = LxnsBindMethod.unique_code
    unique_code: str = Field(min_length=4, max_length=128)


class LxnsApiKeyCredential(BaseModel):
    method: Literal[LxnsBindMethod.api_key] = LxnsBindMethod.api_key
    api_key: SecretStr = Field(description="敏感字段，日志/打印时会自动脱敏")


class LxnsOAuthCredential(BaseModel):
    """这里的 OA 指 LXNS OAuth2.0 授权绑定（你现有代码里也叫 oa_client）。"""

    method: Literal[LxnsBindMethod.oa] = LxnsBindMethod.oa

    access_token: SecretStr
    refresh_token: SecretStr

    token_expiry: datetime = Field(description="access_token 过期时间")
    refresh_expiry: Optional[datetime] = Field(default=None, description="refresh_token 过期时间（如有）")


LxnsCredential = Union[LxnsUniqueCodeCredential, LxnsApiKeyCredential, LxnsOAuthCredential]


class LxnsBindRequest(BaseModel):
    """绑定请求：面向业务层/接口层。"""

    qq: str = Field(description="用于定位用户的 QQ 号（主键仍为自增 User.id）")
    credential: LxnsCredential = Field(discriminator="method")
    operator: Optional[str] = None


class LxnsBindResult(BaseModel):
    user_id: int
    qq: str
    platform: Literal[LxnsProvider.lxns] = LxnsProvider.lxns
    account_name: str = Field(description="落库用的 account_name")
    account_key: str = Field(description="落库用的 account_key（见 LxnsAccountKey 规则）")
    schema_version: int = 1
    stored_at: datetime


class LxnsAccountKeyType(str, Enum):
    """用于构造 UserAccount.account_key，保证唯一且可检索。"""

    unique_code = "unique_code"
    api_key = "api_key"
    oa = "oa"


class LxnsAccountKey(BaseModel):
    """将三种绑定方式归一成一个 account_key。"""

    type: LxnsAccountKeyType
    value: str

    def to_string(self) -> str:
        return f"{self.type.value}:{self.value}"


class LxnsAccountJsonV1(BaseModel):
    """存入 UserAccount.account_json 的结构（schema_version=1）。"""

    provider: Literal[LxnsProvider.lxns] = LxnsProvider.lxns
    method: LxnsBindMethod

    unique_code: Optional[str] = None
    api_key: Optional[SecretStr] = None

    oauth2_access_token: Optional[SecretStr] = None
    oauth2_refresh_token: Optional[SecretStr] = None
    oauth2_token_expiry: Optional[datetime] = None
    oauth2_refresh_expiry: Optional[datetime] = None

    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_updated_at: datetime = Field(default_factory=datetime.utcnow)

    extra: Dict[str, Any] = Field(default_factory=dict)


class GameProfileV1(BaseModel):
    maimai_name: Optional[str] = None
    maimai_friend_code: Optional[str] = None
    chunithm_name: Optional[str] = None
    chunithm_friend_code: Optional[str] = None

    updated_at: Optional[datetime] = None


class LxnsExternalSnapshot(BaseModel):
    user_id: str
    fetched_at: datetime
    data_type: str
    data: Dict[str, Any]
    source: Literal[LxnsProvider.lxns] = LxnsProvider.lxns
