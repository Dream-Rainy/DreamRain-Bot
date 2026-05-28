from __future__ import annotations

import datetime
from unittest.mock import patch

import pytest
import pytest_asyncio
from tortoise import Tortoise


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
                    "models": ["src.plugins.chiffon_bot.infra.db.models"],
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
    """_do_bind 应创建 User → UserAccount → GameProfile 链路。"""
    from src.plugins.chiffon_bot.integrations.lxns.use_cases.bind_oauth import _do_bind
    from src.plugins.chiffon_bot.integrations.lxns.use_cases.bind_oauth import http_client as bind_http
    from src.plugins.chiffon_bot.infra.db.models import GameProfile, UserAccount, QQ_PLATFORM

    now = datetime.datetime.now(datetime.UTC)

    with patch.object(bind_http, "get_json") as mock_get:
        mock_get.side_effect = [
            {"data": {"name": "MaiPlayer", "friend_code": "1234567890"}},
            {"data": {"name": "", "friend_code": ""}},
        ]

        token_data = {
            "access_token": "access_test",
            "refresh_token": "refresh_test",
            "token_expiry": now + datetime.timedelta(seconds=900),
            "refresh_expiry": now + datetime.timedelta(days=30),
        }

        result = await _do_bind(qq="12345678", token_data=token_data)

    assert result.status == "bound"
    assert result.account_key != ""

    # 验证 QQ UserAccount 已创建
    qq_link = await UserAccount.get_or_none(platform=QQ_PLATFORM, account_key="12345678")
    assert qq_link is not None

    # 验证 LXNS UserAccount 已创建（记在同一个 User 下）
    lxns_account = await UserAccount.get_or_none(platform="lxns", account_key=result.account_key)
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
    """bind_by_oauth_code（回调路径）端到端应成功。"""
    from src.plugins.chiffon_bot.integrations.lxns.use_cases.bind_oauth import bind_by_oauth_code
    from src.plugins.chiffon_bot.integrations.lxns.use_cases.bind_oauth import http_client as bind_http
    from src.plugins.chiffon_bot.integrations.lxns.oauth_client import http_client as oauth_http
    from src.plugins.chiffon_bot.integrations.lxns.oauth_client import oa_client
    from src.plugins.chiffon_bot.infra.db.models import GameProfile, UserAccount, QQ_PLATFORM

    # 先注册一个 wait_bind_user（模拟 /acc.bind 无参生成链接的过程）
    qq = "99999999"
    state = oa_client.add_wait_bind_user(qq)

    with patch.object(bind_http, "get_json") as mock_get, \
         patch.object(oauth_http, "post_json") as mock_post:

        mock_post.return_value = {
            "data": {
                "access_token": "callback_token",
                "refresh_token": "callback_refresh",
                "token_type": "Bearer",
                "expires_in": 900,
                "scope": "read_player",
            }
        }

        mock_get.side_effect = [
            {"data": {"name": "MaiCallback", "friend_code": "5555555555"}},
            {"data": {"name": "ChuniCallback", "friend_code": "6666666666"}},
        ]

        result = await bind_by_oauth_code(qq=qq, code="auth_code_cb", state=state)

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
    """bind_by_oauth_code 在 get_token 失败时应返回 error。"""
    from src.plugins.chiffon_bot.integrations.lxns.use_cases.bind_oauth import bind_by_oauth_code
    from src.plugins.chiffon_bot.integrations.lxns.oauth_client import http_client as oauth_http
    from src.plugins.chiffon_bot.integrations.lxns.oauth_client import oa_client
    from src.plugins.chiffon_bot.infra.db.models import UserAccount, QQ_PLATFORM

    qq = "bad_callback_user"
    state = oa_client.add_wait_bind_user(qq)

    with patch.object(oauth_http, "post_json") as mock_post:
        mock_post.return_value = {"data": {}}  # 没有 access_token → ValueError

        result = await bind_by_oauth_code(qq=qq, code="bad_code", state=state)

    assert result.status == "error"

    qq_link = await UserAccount.get_or_none(platform=QQ_PLATFORM, account_key=qq)
    assert qq_link is None
