"""End-to-end tests against a running API server."""

import os
import json
import pytest
import httpx
from claude_code_api.models.claude import get_default_model


BASE_URL = os.getenv("CLAUDE_CODE_API_BASE_URL", "http://localhost:8000")


def _should_run_e2e() -> bool:
    return os.getenv("CLAUDE_CODE_API_E2E") == "1"


@pytest.fixture(scope="session")
def live_client():
    if not _should_run_e2e():
        pytest.skip("Set CLAUDE_CODE_API_E2E=1 to run live API tests.")

    try:
        response = httpx.get(f"{BASE_URL}/health", timeout=5)
        if response.status_code != 200:
            pytest.skip(f"API not healthy at {BASE_URL}.")
    except Exception as exc:
        pytest.skip(f"API not reachable at {BASE_URL}: {exc}")

    with httpx.Client(base_url=BASE_URL, timeout=60) as client:
        yield client


def _parse_sse_lines(lines):
    events = []
    for line in lines:
        if not line.startswith("data: "):
            continue
        payload = line[6:]
        if payload == "[DONE]":
            break
        events.append(json.loads(payload))
    return events


@pytest.mark.e2e
def test_live_health(live_client):
    response = live_client.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload.get("status") == "healthy"


@pytest.mark.e2e
def test_live_models(live_client):
    response = live_client.get("/v1/models")
    assert response.status_code == 200
    payload = response.json()
    assert payload.get("object") == "list"
    assert payload.get("data")


@pytest.mark.e2e
def test_live_chat_completion(live_client):
    payload = {
        "model": get_default_model(),
        "messages": [{"role": "user", "content": "Say only 'hi'."}],
        "stream": False
    }
    response = live_client.post("/v1/chat/completions", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data.get("object") == "chat.completion"
    assert data.get("choices")


@pytest.mark.e2e
def test_live_chat_streaming(live_client):
    payload = {
        "model": get_default_model(),
        "messages": [{"role": "user", "content": "Say only 'hi'."}],
        "stream": True
    }
    with live_client.stream("POST", "/v1/chat/completions", json=payload) as response:
        assert response.status_code == 200
        lines = [line for line in response.iter_lines() if line]
    events = _parse_sse_lines(lines)
    assert any(event.get("object") == "chat.completion.chunk" for event in events)
