"""Tests for parser utilities."""

import json
from types import SimpleNamespace

from claude_code_api.models.claude import ClaudeMessage, ClaudeToolUse
from claude_code_api.utils.parser import (
    ClaudeOutputParser,
    MessageAggregator,
    estimate_tokens,
    extract_error_from_message,
    format_timestamp,
    normalize_claude_message,
    sanitize_content,
    tool_use_to_openai_call,
)


def _message_with_content(content):
    return ClaudeMessage(
        type="assistant",
        message={"role": "assistant", "content": content},
        session_id="sess",
        model="claude",
    )


def test_extract_text_content_variants():
    parser = ClaudeOutputParser()
    assert parser.extract_text_content(_message_with_content("plain")) == "plain"
    assert (
        parser.extract_text_content(_message_with_content({"text": "nested"}))
        == "nested"
    )
    assert (
        parser.extract_text_content(_message_with_content({"content": "inner"}))
        == "inner"
    )

    content = [{"type": "text", "text": "hello"}, "world", {"content": "x"}]
    assert (
        parser.extract_text_content(_message_with_content(content)) == "hello\nworld\nx"
    )

    assert parser.extract_text_content(_message_with_content(123)) == "123"


def test_extract_tool_uses_and_results():
    parser = ClaudeOutputParser()
    message = ClaudeMessage(
        type="assistant",
        message={
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": "tool1",
                    "name": "bash",
                    "input": {"command": "ls"},
                }
            ],
        },
    )
    tool_uses = parser.extract_tool_uses(message)
    assert tool_uses
    assert tool_uses[0].name == "bash"

    result_message = ClaudeMessage(
        type="tool_result",
        message={
            "role": "tool",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "tool1",
                    "content": "ok",
                    "is_error": False,
                }
            ],
        },
    )
    results = parser.extract_tool_results(result_message)
    assert results
    assert results[0].tool_use_id == "tool1"


def test_parse_message_updates_metrics():
    parser = ClaudeOutputParser()
    message = ClaudeMessage(
        type="assistant",
        message={"role": "assistant", "content": "hi"},
        session_id="sess",
        model="claude",
        usage={"input_tokens": 3, "output_tokens": 5},
        cost_usd=0.01,
    )
    parser.parse_message(message)
    assert parser.session_id == "sess"
    assert parser.model == "claude"
    assert parser.total_tokens == 8
    assert parser.total_cost == 0.01
    assert parser.message_count == 1


def test_error_extraction_helpers():
    message = ClaudeMessage(type="error", error="boom")
    assert extract_error_from_message(message) == "boom"

    message = ClaudeMessage(type="result", result=None)
    assert extract_error_from_message(message) == "Execution completed without result"

    message = ClaudeMessage(
        type="tool_result",
        message={
            "role": "tool",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "tool1",
                    "content": "bad",
                    "is_error": True,
                }
            ],
        },
    )
    assert extract_error_from_message(message) == "bad"


def test_misc_utilities():
    assert estimate_tokens("1234") >= 1
    assert sanitize_content("a\x00b") == "ab"
    assert "?" in sanitize_content("bad\udcff")

    assert normalize_claude_message({"type": "assistant"}).type == "assistant"
    assert normalize_claude_message(["not", "a", "dict"]) is None

    tool_use = ClaudeToolUse(id="", name="bash", input={"command": "ls"})
    call = tool_use_to_openai_call(tool_use)
    assert call["function"]["name"] == "bash"

    tool_use = SimpleNamespace(id="", name="bash", input=set([1, 2]))
    call = tool_use_to_openai_call(tool_use)
    assert "input" in json.loads(call["function"]["arguments"])

    assert "T" in format_timestamp(None)
    assert format_timestamp("2026-02-04T00:00:00Z").startswith("2026-02-04T")


def test_message_aggregator():
    aggregator = MessageAggregator()
    aggregator.add_message(
        {
            "type": "assistant",
            "message": {"role": "assistant", "content": "hello"},
            "session_id": "sess",
        }
    )
    aggregator.add_message(
        {
            "type": "assistant",
            "message": {"role": "assistant", "content": " world"},
            "session_id": "sess",
        }
    )
    assert aggregator.get_complete_response() == "hello world"


def test_parse_line_invalid_json():
    parser = ClaudeOutputParser()
    assert parser.parse_line("{not-json}") is None
