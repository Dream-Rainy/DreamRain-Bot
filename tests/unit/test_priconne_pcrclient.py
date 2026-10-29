from __future__ import annotations

import pytest
import asyncio
import httpx


@pytest.fixture
def transport_client(app, monkeypatch):
    from src.plugins.priconne import pcrclient as module

    clients, waits = [], []

    def build(handler):
        def factory(cookies=None):
            client = httpx.AsyncClient(transport=httpx.MockTransport(handler), cookies=cookies)
            clients.append(client)
            return client

        monkeypatch.setattr(module.pcrclient, '_make_http_client', staticmethod(factory))
        client = make_client(module)
        client.call_lock = asyncio.Lock()
        client.headers = {'SID': 'secret-session', 'REQUEST-ID': 'request-1'}
        client.client = factory({'affinity': 'node-1'})
        return client

    async def sleep(delay):
        waits.append(delay)

    monkeypatch.setattr(module.asyncio, 'sleep', sleep)
    return module, build, clients, waits


async def test_read_error_rebuilds_pool_and_preserves_session(transport_client):
    module, build, clients, waits = transport_client
    requests = []

    def handler(request):
        requests.append(request)
        if len(requests) == 1:
            raise httpx.ReadError('', request=request)
        return httpx.Response(200, json={'data_headers': {}, 'data': {'ok': True}})

    client = build(handler)
    original = {'carrier': 'OPPO'}
    try:
        assert await client.callapi('/load/index', original, crypted=False) == {'ok': True}
        assert waits == [.5] and len(clients) == 2 and clients[0].is_closed
        assert original == {'carrier': 'OPPO'}
        assert requests[0].content == requests[1].content
        assert requests[1].headers['SID'] == 'secret-session'
        assert requests[1].headers['REQUEST-ID'] == 'request-1'
        assert 'affinity=node-1' in requests[1].headers['cookie']
    finally:
        await client.client.aclose()


@pytest.mark.parametrize(('path', 'failure', 'attempts', 'network'), [
    ('/load/index', 'read', 3, True),
    ('/session/login', 'read', 1, True),
    ('/clan_battle/battle_start', 'read', 1, True),
    ('/load/index', 'json', 1, False),
])
async def test_only_safe_queries_retry_transport_failures(transport_client, path, failure, attempts, network):
    module, build, clients, waits = transport_client
    calls = []

    def handler(request):
        calls.append(request)
        if failure == 'read':
            raise httpx.ReadError('', request=request)
        return httpx.Response(200, content=b'invalid json')

    client = build(handler)
    try:
        with pytest.raises(module.ApiException) as caught:
            await client.callapi(path, {}, crypted=False, noerr=False)
        assert caught.value.code == 501
        assert module._is_network_error(caught.value) is network
        assert len(calls) == attempts and waits == [.5, 1][:attempts - 1]
    finally:
        await client.client.aclose()


@pytest.mark.parametrize(('status', 'noerr', 'attempts'), [(5, False, 3), (5, True, 3), (3, False, 1)])
async def test_game_errors_keep_codes_and_backoff(transport_client, status, noerr, attempts):
    module, build, clients, waits = transport_client
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={'data_headers': {'result_code': 500},
                                        'data': {'server_error': {'status': status, 'message': 'temporary'}}})

    client = build(handler)
    try:
        if noerr:
            assert (await client.callapi('/load/index', {}, crypted=False))['server_error']['status'] == status
        else:
            with pytest.raises(module.ApiException) as caught:
                await client.callapi('/load/index', {}, crypted=False, noerr=False)
            assert caught.value.code == status and caught.value.result_code == 500
        assert len(calls) == attempts and waits == [.5, 1][:attempts - 1]
        assert len(clients) == 1
    finally:
        await client.client.aclose()


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
