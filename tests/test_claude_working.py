"""Fixture-based tests for Claude CLI output parsing."""

import json
from pathlib import Path

from claude_code_api.utils.streaming import create_non_streaming_response
from tests.model_utils import get_test_model_id

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture(filename: str):
    path = FIXTURES_DIR / filename
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def test_fixture_simple_non_streaming_response():
    """Ensure basic fixture output produces a valid response."""
    messages = load_fixture("claude_stream_simple.jsonl")
    response = create_non_streaming_response(
        messages=messages, session_id="sess_simple_1", model=get_test_model_id()
    )

    choice = response["choices"][0]
    assert choice["message"]["role"] == "assistant"
    assert choice["message"]["content"].startswith("Hello!")
    assert response["usage"]["total_tokens"] >= 0


def test_fixture_tool_calls_response():
    """Ensure tool calls are surfaced from fixture output."""
    messages = load_fixture("claude_stream_tool_calls.jsonl")
    response = create_non_streaming_response(
        messages=messages, session_id="sess_tool_1", model=get_test_model_id()
    )

    message = response["choices"][0]["message"]
    assert "tool_calls" in message
    assert len(message["tool_calls"]) > 0
    assert message["tool_calls"][0]["function"]["name"] == "bash"


def test_tool_calls_without_text_finish_reason():
    """Tool-only responses should report tool_calls finish reason."""
    messages = [
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_1",
                        "name": "bash",
                        "input": {"command": "ls"},
                    }
                ],
            },
            "session_id": "sess_tool_only",
            "model": get_test_model_id(),
        },
        {
            "type": "result",
            "result": "ok",
            "session_id": "sess_tool_only",
            "model": get_test_model_id(),
            "usage": {"input_tokens": 5, "output_tokens": 5},
        },
    ]
    response = create_non_streaming_response(
        messages=messages, session_id="sess_tool_only", model=get_test_model_id()
    )

    choice = response["choices"][0]
    assert choice["finish_reason"] == "tool_calls"
    assert choice["message"]["content"] in ("", None)
