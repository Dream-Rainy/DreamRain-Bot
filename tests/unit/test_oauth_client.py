from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_add_and_get_wait_bind_user(loaded_chiffon_bot):
    """add_wait_bind_user 应创建可查询的等待记录。"""
    from src.plugins.chiffon_bot.integrations.lxns.client import lxns_client

    oa_client = lxns_client.oauth
    state = oa_client.add_wait_bind_user("12345678")
    record = oa_client.get_wait_bind_user(state)
    assert record is not None
    assert record["user_id_hash"] == "12345678"
    assert record["state"] == state


@pytest.mark.asyncio
async def test_validate_wait_bind_user_rejects_wrong_user(loaded_chiffon_bot):
    """validate_wait_bind_user 在 user_id_hash 不匹配时应抛出 ValueError。"""
    from src.plugins.chiffon_bot.integrations.lxns.client import lxns_client

    oa_client = lxns_client.oauth
    state = oa_client.add_wait_bind_user("correct_user")
    with pytest.raises(ValueError, match="状态不匹配"):
        oa_client.validate_wait_bind_user(state, user_id_hash="wrong_user")


@pytest.mark.asyncio
async def test_remove_wait_bind_user(loaded_chiffon_bot):
    """remove_wait_bind_user 应清除该用户所有等待记录。"""
    from src.plugins.chiffon_bot.integrations.lxns.client import lxns_client

    oa_client = lxns_client.oauth
    oa_client.add_wait_bind_user("remove_me")
    oa_client.remove_wait_bind_user("remove_me")

    # 验证清空后无记录
    records = [s for s, d in oa_client.wait_bind_user.items() if d.get("user_id_hash") == "remove_me"]
    assert len(records) == 0


@pytest.mark.asyncio
async def test_mark_and_get_bind_result(loaded_chiffon_bot):
    """mark_bind_result 存入后可通过 user 和 state 查询。"""
    from src.plugins.chiffon_bot.integrations.lxns.client import lxns_client

    oa_client = lxns_client.oauth
    oa_client.mark_bind_result(
        state="st_result",
        user_id_hash="user_result",
        status="bound",
        message="ok",
        account_key="key_1",
    )

    by_user = oa_client.get_bind_result_by_user("user_result")
    assert by_user is not None
    assert by_user["status"] == "bound"
    assert by_user["account_key"] == "key_1"

    by_state = oa_client.get_bind_result_by_state("st_result")
    assert by_state is not None
    assert by_state["status"] == "bound"


@pytest.mark.asyncio
async def test_cleanup_expired_wait_bind_user(loaded_chiffon_bot, monkeypatch):
    """cleanup_wait_bind_user 应清除过期的记录。"""
    from datetime import UTC, datetime, timedelta
    from src.plugins.chiffon_bot.integrations.lxns.client import lxns_client

    oa_client = lxns_client.oauth
    state = oa_client.add_wait_bind_user("expire_user")

    # 将 created_at 伪造成 30 天前
    oa_client.wait_bind_user[state]["created_at"] = datetime.now(UTC) - timedelta(days=30)
    oa_client.cleanup_wait_bind_user()

    assert oa_client.get_wait_bind_user(state) is None
