"""Tests for auth utilities and middleware."""

import json

import pytest
from fastapi.responses import JSONResponse
from starlette.requests import Request

from claude_code_api.core import auth as auth_module
from claude_code_api.core.config import settings


def _build_request(
    path: str = "/v1/models", headers=None, query_string: bytes = b""
) -> Request:
    headers = headers or []
    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "headers": headers,
        "query_string": query_string,
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
        "scheme": "http",
    }
    return Request(scope)


def test_extract_api_key_sources():
    request = _build_request(headers=[(b"authorization", b"Bearer secret")])
    assert auth_module.extract_api_key(request) == "secret"

    request = _build_request(headers=[(b"x-api-key", b"apikey")])
    assert auth_module.extract_api_key(request) == "apikey"

    request = _build_request(query_string=b"api_key=querykey")
    assert auth_module.extract_api_key(request) == "querykey"

    request = _build_request()
    assert auth_module.extract_api_key(request) is None


def test_rate_limiter_basic():
    limiter = auth_module.RateLimiter(requests_per_minute=2, burst=10)
    assert limiter.is_allowed("client") is True
    assert limiter.is_allowed("client") is True
    assert limiter.is_allowed("client") is False


def test_rate_limiter_burst_reset(monkeypatch):
    limiter = auth_module.RateLimiter(requests_per_minute=100, burst=1)
    now = [100.0]
    monkeypatch.setattr(auth_module.time, "time", lambda: now[0])
    assert limiter.is_allowed("client") is True
    # Move time forward so requests are cleared, but burst_used is still set.
    now[0] += 61.0
    assert limiter.is_allowed("client") is True


def test_validate_api_key_toggle():
    original_require_auth = settings.require_auth
    original_keys = list(settings.api_keys)
    try:
        settings.require_auth = False
        settings.api_keys = ["secret"]
        assert auth_module.validate_api_key("secret") is True

        settings.require_auth = True
        settings.api_keys = []
        assert auth_module.validate_api_key("secret") is False

        settings.api_keys = ["secret"]
        assert auth_module.validate_api_key("secret") is True
        assert auth_module.validate_api_key("bad") is False
    finally:
        settings.require_auth = original_require_auth
        settings.api_keys = original_keys


@pytest.mark.asyncio
async def test_auth_middleware_allows_when_disabled():
    original_require_auth = settings.require_auth
    settings.require_auth = False
    captured = {}

    async def call_next(req: Request):
        captured["api_key"] = req.state.api_key
        captured["client_id"] = req.state.client_id
        return JSONResponse({"ok": True})

    request = _build_request()
    response = await auth_module.auth_middleware(request, call_next)
    assert response.status_code == 200
    assert captured["api_key"] is None
    assert captured["client_id"] == "testclient"

    settings.require_auth = original_require_auth


@pytest.mark.asyncio
async def test_auth_middleware_missing_key():
    original_require_auth = settings.require_auth
    original_keys = list(settings.api_keys)
    settings.require_auth = True
    settings.api_keys = ["secret"]

    request = _build_request()

    async def call_next(req: Request):
        return JSONResponse({"ok": True})

    response = await auth_module.auth_middleware(request, call_next)
    assert response.status_code == 401
    payload = response.json() if hasattr(response, "json") else None
    if payload is None:
        payload = json.loads(response.body.decode())
    assert payload["error"]["code"] == "missing_api_key"

    settings.require_auth = original_require_auth
    settings.api_keys = original_keys


@pytest.mark.asyncio
async def test_auth_middleware_invalid_key():
    original_require_auth = settings.require_auth
    original_keys = list(settings.api_keys)
    settings.require_auth = True
    settings.api_keys = ["secret"]

    request = _build_request(headers=[(b"authorization", b"Bearer bad")])

    async def call_next(req: Request):
        return JSONResponse({"ok": True})

    response = await auth_module.auth_middleware(request, call_next)
    assert response.status_code == 401
    payload = response.json() if hasattr(response, "json") else None
    if payload is None:
        payload = json.loads(response.body.decode())
    assert payload["error"]["code"] == "invalid_api_key"

    settings.require_auth = original_require_auth
    settings.api_keys = original_keys


@pytest.mark.asyncio
async def test_auth_middleware_rate_limited(monkeypatch):
    original_require_auth = settings.require_auth
    original_keys = list(settings.api_keys)
    settings.require_auth = True
    settings.api_keys = ["secret"]

    monkeypatch.setattr(auth_module.rate_limiter, "is_allowed", lambda _key: False)

    request = _build_request(headers=[(b"authorization", b"Bearer secret")])

    async def call_next(req: Request):
        return JSONResponse({"ok": True})

    response = await auth_module.auth_middleware(request, call_next)
    assert response.status_code == 429
    payload = response.json() if hasattr(response, "json") else None
    if payload is None:
        payload = json.loads(response.body.decode())
    assert payload["error"]["code"] == "rate_limit_exceeded"

    settings.require_auth = original_require_auth
    settings.api_keys = original_keys


@pytest.mark.asyncio
async def test_auth_middleware_valid_key():
    original_require_auth = settings.require_auth
    original_keys = list(settings.api_keys)
    settings.require_auth = True
    settings.api_keys = ["secret"]
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(auth_module.rate_limiter, "is_allowed", lambda _key: True)

    captured = {}

    async def call_next(req: Request):
        captured["api_key"] = req.state.api_key
        captured["client_id"] = req.state.client_id
        return JSONResponse({"ok": True})

    request = _build_request(headers=[(b"authorization", b"Bearer secret")])
    response = await auth_module.auth_middleware(request, call_next)
    assert response.status_code == 200
    assert captured["api_key"] == "secret"
    assert captured["client_id"] == "secret"

    monkeypatch.undo()
    settings.require_auth = original_require_auth
    settings.api_keys = original_keys
