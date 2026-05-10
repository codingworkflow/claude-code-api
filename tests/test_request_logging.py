"""Tests for HTTP request access logging middleware."""

import asyncio
from types import SimpleNamespace

from claude_code_api import main as main_module


class FakeLogger:
    def __init__(self):
        self.calls = []

    def info(self, *args, **kwargs):
        self.calls.append((args, kwargs))


def _request(path: str = "/health"):
    return SimpleNamespace(
        method="GET",
        url=SimpleNamespace(path=path),
        client=SimpleNamespace(host="127.0.0.1"),
    )


async def _response(request):
    return SimpleNamespace(status_code=204)


def test_request_logging_middleware_skips_when_access_log_disabled(monkeypatch):
    fake_logger = FakeLogger()
    monkeypatch.setattr(main_module.settings, "access_log", False)
    monkeypatch.setattr(main_module, "logger", fake_logger)

    response = asyncio.run(
        main_module.request_logging_middleware(_request(), _response)
    )

    assert response.status_code == 204
    assert fake_logger.calls == []


def test_request_logging_middleware_logs_when_access_log_enabled(monkeypatch):
    fake_logger = FakeLogger()
    monkeypatch.setattr(main_module.settings, "access_log", True)
    monkeypatch.setattr(main_module, "logger", fake_logger)

    response = asyncio.run(
        main_module.request_logging_middleware(_request("/v1/models"), _response)
    )

    assert response.status_code == 204
    assert len(fake_logger.calls) == 1

    args, kwargs = fake_logger.calls[0]
    assert args == ("HTTP request",)
    assert kwargs["access_log"] is True
    assert kwargs["method"] == "GET"
    assert kwargs["path"] == "/v1/models"
    assert kwargs["status_code"] == 204
    assert kwargs["client_host"] == "127.0.0.1"
    assert isinstance(kwargs["duration_ms"], float)
