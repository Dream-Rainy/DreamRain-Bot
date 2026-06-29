from __future__ import annotations

import datetime
from unittest.mock import patch

import pytest
import pytest_asyncio
from tortoise import Tortoise

from arcade_helper.storage.tortoise import MODEL_MODULE as ARCADE_HELPER_MODEL_MODULE


BOT_MODEL_MODULE = "src.plugins.chiffon_bot.infra.db.models"


@pytest_asyncio.fixture
async def oauth_db(tmp_path):
    """初始化 Tortoise（仅 User/UserAccount/GameProfile 表），不种子数据。"""
    db_path = tmp_path / "oauth.sqlite3"
    await Tortoise.init(
        {
            "connections": {
                "default": {
                    "engine": "tortoise.backends.sqlite",
                    "credentials": {"file_path": str(db_path)},
                }
            },
            "apps": {
                "models": {
                    "models": [ARCADE_HELPER_MODEL_MODULE, BOT_MODEL_MODULE],
                    "default_connection": "default",
                }
            },
        },
        _create_db=True,
    )
    await Tortoise.generate_schemas()
    try:
        yield
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_do_bind_creates_account_and_profile(loaded_chiffon_bot, oauth_db):
    """bind_lxns_token_data 应创建 User → UserAccount → GameProfile 链路。"""
    from src.plugins.chiffon_bot.integrations.lxns.client import lxns_client
    from arcade_helper.users import PlatformIdentity
    from arcade_helper.storage.tortoise import GameProfile, QQ_PLATFORM, UserAccount

    await lxns_client.data.lifecycle.start()

    now = datetime.datetime.now(datetime.UTC)

    with patch.object(lxns_client.maimai, "user_player") as mock_mai_user, \
         patch.object(lxns_client.chunithm, "user_player") as mock_chuni_user:
        mock_mai_user.return_value = {"data": {"name": "MaiPlayer", "friend_code": "1234567890"}}
        mock_chuni_user.return_value = {"data": {"name": "", "friend_code": ""}}
        token_data = {
            "access_token": "access_test",
            "refresh_token": "refresh_test",
            "token_expiry": now + datetime.timedelta(seconds=900),
            "refresh_expiry": now + datetime.timedelta(days=30),
        }

        result = await lxns_client.data.auth.bind_lxns_token_data(
            identity=PlatformIdentity.qq("12345678"),
            token_data=token_data,
        )

    assert result.status == "bound"
    assert result.lxns_account_key != ""

    # 验证 QQ UserAccount 已创建
    qq_link = await UserAccount.get_or_none(platform=QQ_PLATFORM, account_key="12345678")
    assert qq_link is not None

    # 验证 LXNS UserAccount 已创建（记在同一个 User 下）
    lxns_account = await UserAccount.get_or_none(platform="lxns", account_key=result.lxns_account_key)
    assert lxns_account is not None
    assert lxns_account.is_default

    # 验证 GameProfile（挂在 LXNS account 上）
    gp = await GameProfile.get_or_none(account=lxns_account)
    assert gp is not None
    assert gp.maimai_name == "MaiPlayer"
    assert gp.maimai_friend_code == "1234567890"
    assert not gp.chunithm_name
    assert not gp.chunithm_friend_code


@pytest.mark.asyncio
async def test_bind_by_oauth_code_success(loaded_chiffon_bot, oauth_db):
    """complete_lxns_oauth（回调路径）端到端应成功。"""
    from src.plugins.chiffon_bot.integrations.lxns.client import lxns_client
    from arcade_helper.users import PlatformIdentity
    from arcade_helper.storage.tortoise import GameProfile, QQ_PLATFORM, UserAccount

    await lxns_client.data.lifecycle.start()

    # 先注册一个 wait_bind_user（模拟 /acc.bind 无参生成链接的过程）
    qq = "99999999"
    identity = PlatformIdentity.qq(qq)
    state = lxns_client.data.auth.start_lxns_oauth(identity).state

    with patch.object(lxns_client.maimai, "user_player") as mock_mai_user, \
         patch.object(lxns_client.chunithm, "user_player") as mock_chuni_user, \
         patch.object(lxns_client.oauth, "http_post_json") as mock_post:

        mock_post.return_value = {
            "access_token": "callback_token",
            "refresh_token": "callback_refresh",
            "token_type": "Bearer",
            "expires_in": 900,
            "scope": "read_player",
        }

        mock_mai_user.return_value = {"data": {"name": "MaiCallback", "friend_code": "5555555555"}}
        mock_chuni_user.return_value = {"data": {"name": "ChuniCallback", "friend_code": "6666666666"}}

        result = await lxns_client.data.auth.complete_lxns_oauth(
            identity=identity,
            code="auth_code_cb",
            state=state,
        )

    assert result.status == "bound"
    assert result.account_key

    qq_link = await UserAccount.get_or_none(platform=QQ_PLATFORM, account_key=qq)
    assert qq_link is not None

    lxns_account = await UserAccount.get_or_none(platform="lxns", account_key=result.account_key)
    assert lxns_account is not None

    gp = await GameProfile.get_or_none(account=lxns_account)
    assert gp is not None
    assert gp.maimai_name == "MaiCallback"
    assert gp.maimai_friend_code == "5555555555"
    assert gp.chunithm_name == "ChuniCallback"
    assert gp.chunithm_friend_code == "6666666666"


@pytest.mark.asyncio
async def test_bind_by_oauth_code_get_token_error(loaded_chiffon_bot, oauth_db):
    """complete_lxns_oauth 在 get_token 失败时应返回 error。"""
    from src.plugins.chiffon_bot.integrations.lxns.client import lxns_client
    from arcade_helper.users import PlatformIdentity
    from arcade_helper.storage.tortoise import QQ_PLATFORM, UserAccount

    await lxns_client.data.lifecycle.start()

    qq = "bad_callback_user"
    identity = PlatformIdentity.qq(qq)
    state = lxns_client.data.auth.start_lxns_oauth(identity).state

    with patch.object(lxns_client.oauth, "http_post_json") as mock_post:
        mock_post.return_value = {"data": {}}  # 没有 access_token → ValueError

        result = await lxns_client.data.auth.complete_lxns_oauth(
            identity=identity,
            code="bad_code",
            state=state,
        )

    assert result.status == "error"

    qq_link = await UserAccount.get_or_none(platform=QQ_PLATFORM, account_key=qq)
    assert qq_link is None
