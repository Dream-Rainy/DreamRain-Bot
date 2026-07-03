from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_get_bytes_uses_cache(tmp_path, monkeypatch):
    from src.plugins.chiffon_bot.infra.http import client as module
    from src.plugins.chiffon_bot.infra.http.client import HttpClient, RetryPolicy

    calls = 0

    class Response:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        def raise_for_status(self):
            return None

        async def read(self):
            return b"image"

        @property
        def status(self):
            return 200

    class Session:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        def get(self, *_args, **_kwargs):
            nonlocal calls
            calls += 1
            return Response()

    monkeypatch.setattr(module.aiohttp, "ClientSession", Session)
    client = HttpClient(cache_dir=str(tmp_path), retry=RetryPolicy(retries=0))

    assert await client.get_bytes("https://example.test/image.png") == b"image"
    assert await client.get_bytes("https://example.test/image.png") == b"image"
    assert calls == 1
