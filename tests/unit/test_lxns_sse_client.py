from __future__ import annotations

import asyncio

import pytest

from arcade_helper.integrations.lxns.sse import SseRelayClient


class _IdleRelayClient(SseRelayClient):
    async def _connect_loop(self) -> None:
        while self._running:
            await asyncio.sleep(1)


@pytest.mark.asyncio
async def test_sse_relay_client_resolves_registered_state_without_nonebot() -> None:
    client = SseRelayClient()

    future = client.register("state-1")
    client._event_received({"state": "state-1", "code": "oauth-code"})

    assert await future == "oauth-code"


@pytest.mark.asyncio
async def test_sse_relay_client_unregister_removes_pending_state() -> None:
    client = SseRelayClient()

    future = client.register("state-2")
    client.unregister("state-2")
    client._event_received({"state": "state-2", "code": "oauth-code"})

    assert not future.done()


@pytest.mark.asyncio
async def test_sse_relay_client_ignores_heartbeat_comments() -> None:
    client = SseRelayClient()

    future = client.register("state-3")
    client._feed_sse_chunk("", b": connected\n\n: heartbeat\n\n")

    assert not future.done()


@pytest.mark.asyncio
async def test_sse_relay_client_register_for_oauth_reuses_active_connection() -> None:
    client = _IdleRelayClient(relay_url="https://relay.example", relay_token="token", idle_stop_seconds=0)

    await client.register_for_oauth("state-4")
    task = client._task
    await client.register_for_oauth("state-5")

    assert task is not None
    assert client._task is task

    client.unregister("state-4")
    client.unregister("state-5")
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert client._running is False
    with pytest.raises(asyncio.CancelledError):
        await task
    assert task.done()
