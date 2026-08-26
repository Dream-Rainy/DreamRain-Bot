from __future__ import annotations

import pytest


class FakeBsdkClient:
    platform = "2"
    qudao = 0


def make_client(module):
    client = object.__new__(module.pcrclient)
    client.bsdk = FakeBsdkClient()
    client.headers = {}
    client.viewer_id = 0
    client.servers = list(module.DEFAULT_API_ROOTS)
    client.active_server = 0
    return client


async def test_refresh_servers_uses_dynamic_server_list(app):
    from src.plugins.priconne import pcrclient as module

    client = make_client(module)
    calls = []

    async def fake_callapi(apiurl, request, crypted=True, noerr=True, header=False):
        calls.append((apiurl, request, crypted, noerr, client.current_api_root))
        return {"server": ["game-1.example.com\t", "https://game-2.example.com/"]}

    client.callapi = fake_callapi

    await client.refresh_servers()

    assert calls == [(
        "/source_ini/index?format=json",
        {},
        False,
        False,
        module.DEFAULT_API_ROOTS[0],
    )]
    assert client.servers == ["https://game-1.example.com", "https://game-2.example.com"]
    assert client.current_api_root == "https://game-1.example.com"


async def test_session_login_rotates_node_and_retries_full_flow(app):
    from src.plugins.priconne import pcrclient as module

    client = make_client(module)
    attempts = []

    async def fake_login_once():
        attempts.append(client.current_api_root)
        if len(attempts) < 3:
            raise module.ApiException("请稍后重试", 5, 500)
        return {"daily_reset_time": 123}

    client._login_once = fake_login_once

    result = await client._login_with_current_token(max_attempts=5)

    assert result == {"daily_reset_time": 123}
    assert attempts == list(module.DEFAULT_API_ROOTS)


async def test_session_login_does_not_retry_terminal_error(app):
    from src.plugins.priconne import pcrclient as module

    client = make_client(module)
    attempts = 0

    async def fake_login_once():
        nonlocal attempts
        attempts += 1
        raise module.ApiException("登录状态已失效", 3, 500)

    client._login_once = fake_login_once

    with pytest.raises(module.ApiException) as exc_info:
        await client._login_with_current_token(max_attempts=5)

    assert exc_info.value.code == 3
    assert attempts == 1
    assert client.active_server == 0


async def test_check_gamestart_uses_even_campaign_user(app):
    from src.plugins.priconne import pcrclient as module

    client = make_client(module)
    requests = []

    async def fake_callapi(apiurl, request, crypted=True, noerr=True, header=False):
        requests.append(request.copy())
        return {"now_tutorial": True}, {}

    client.callapi = fake_callapi

    await client.check_gamestart()

    assert len(requests) == 1
    assert requests[0]["campaign_user"] % 2 == 0
    assert requests[0]["campaign_data"] == ""
