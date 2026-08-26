from __future__ import annotations


class FakeLogger:
    def __init__(self):
        self.messages: list[str] = []

    def opt(self, **kwargs):
        return self

    def warning(self, message: str):
        self.messages.append(message)


class FakeClient:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = 0
        self.rotations = 0

    async def callapi(self, apiurl, request):
        self.calls += 1
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response

    def rotate_server(self):
        self.rotations += 1


async def test_check_client_returns_true_for_success(app, monkeypatch):
    from src.plugins.priconne.util import tools

    fake_logger = FakeLogger()
    monkeypatch.setattr(tools, "logger", fake_logger)
    client = FakeClient([{"user_info": {"user_name": "test"}}])

    assert await tools.check_client(client) is True
    assert client.calls == 1
    assert fake_logger.messages == []


async def test_check_client_stops_on_terminal_error_and_redacts_sensitive_values(app, monkeypatch):
    from src.plugins.priconne.util import tools

    fake_logger = FakeLogger()
    monkeypatch.setattr(tools, "logger", fake_logger)
    error = {
        "status": 3,
        "title": "session error",
        "message": "登录状态已失效",
        "access_key": "secret-access-key",
    }
    client = FakeClient([{"server_error": error}])

    assert await tools.check_client(client) is False
    assert client.calls == 1
    assert client.rotations == 0
    assert any("status=3" in message for message in fake_logger.messages)
    assert any("'access_key': '***'" in message for message in fake_logger.messages)
    assert all("secret-access-key" not in message for message in fake_logger.messages)


async def test_check_client_rotates_after_retryable_server_error(app, monkeypatch):
    from src.plugins.priconne.util import tools

    fake_logger = FakeLogger()
    monkeypatch.setattr(tools, "logger", fake_logger)
    client = FakeClient([
        {"server_error": {"status": 5, "message": "请稍后重试"}},
        {"user_info": {"user_name": "test"}},
    ])

    assert await tools.check_client(client) is True
    assert client.calls == 2
    assert client.rotations == 1


async def test_check_client_logs_each_exception_and_retries(app, monkeypatch):
    from src.plugins.priconne.util import tools

    fake_logger = FakeLogger()
    monkeypatch.setattr(tools, "logger", fake_logger)
    client = FakeClient([TimeoutError("timed out")] * 3)

    assert await tools.check_client(client) is False
    assert client.calls == 3
    assert client.rotations == 3
    assert sum("/load/index exception" in message for message in fake_logger.messages) == 3
    assert "attempt=3/3" in fake_logger.messages[-2]
