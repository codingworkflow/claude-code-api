"""Tests for the minimal OpenAI Responses API compatibility route."""

import json

from tests.model_utils import get_test_model_id


DEFAULT_MODEL = get_test_model_id()


def parse_sse_events(body_text: str):
    events = []
    current_event = {"event": None, "data": []}
    for line in body_text.splitlines():
        if not line:
            if current_event["data"]:
                payload = "\n".join(current_event["data"])
                if payload == "[DONE]":
                    events.append({"event": current_event["event"], "data": "[DONE]"})
                else:
                    events.append(
                        {
                            "event": current_event["event"],
                            "data": json.loads(payload),
                        }
                    )
            current_event = {"event": None, "data": []}
            continue

        if line.startswith("event: "):
            current_event["event"] = line[7:]
        elif line.startswith("data: "):
            current_event["data"].append(line[6:])

    return events


def test_responses_string_input(test_client):
    response = test_client.post(
        "/v1/responses",
        json={
            "model": DEFAULT_MODEL,
            "input": "Hi",
            "stream": False,
            "temperature": 0.2,
            "max_output_tokens": 16,
        },
    )

    assert response.status_code == 200
    data = response.json()

    assert data["id"].startswith("resp_")
    assert data["object"] == "response"
    assert data["status"] == "completed"
    assert data["model"] == DEFAULT_MODEL
    assert data["max_output_tokens"] == 16
    assert data["output_text"] == "Hello! How can I help today?"
    assert data["output"][0]["type"] == "message"
    assert data["output"][0]["role"] == "assistant"
    assert data["output"][0]["content"][0]["type"] == "output_text"
    assert data["output"][0]["content"][0]["text"] == data["output_text"]
    assert data["usage"]["input_tokens"] is not None
    assert data["usage"]["output_tokens"] is not None
    assert data["usage"]["total_tokens"] is not None


def test_responses_message_array_input_text_blocks(test_client):
    response = test_client.post(
        "/v1/responses",
        json={
            "model": DEFAULT_MODEL,
            "input": [
                {"role": "system", "content": "Keep replies short."},
                {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "Hi"}],
                },
            ],
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["object"] == "response"
    assert data["output_text"] == "Hello! How can I help today?"


def test_responses_streaming_text_events(test_client):
    response = test_client.post(
        "/v1/responses",
        json={"model": DEFAULT_MODEL, "input": "Hi", "stream": True},
    )

    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]

    events = parse_sse_events(response.text)
    event_names = [event["event"] for event in events]

    assert "response.created" in event_names
    assert "response.output_item.added" in event_names
    assert "response.content_part.added" in event_names
    assert "response.output_text.delta" in event_names
    assert "response.output_text.done" in event_names
    assert "response.content_part.done" in event_names
    assert "response.output_item.done" in event_names
    assert "response.completed" in event_names
    assert events[-1]["data"] == "[DONE]"

    deltas = [
        event["data"]["delta"]
        for event in events
        if event["event"] == "response.output_text.delta"
    ]
    assert "".join(deltas) == "Hello! How can I help today?"

    completed = next(
        event["data"]
        for event in events
        if event["event"] == "response.completed"
    )
    assert completed["response"]["object"] == "response"
    assert completed["response"]["status"] == "completed"
    assert completed["response"]["output_text"] == "Hello! How can I help today?"


def test_responses_rejects_unsupported_content_block(test_client):
    response = test_client.post(
        "/v1/responses",
        json={
            "model": DEFAULT_MODEL,
            "input": [
                {
                    "role": "user",
                    "content": [{"type": "input_image", "image_url": "https://x"}],
                }
            ],
        },
    )

    assert response.status_code == 400
    data = response.json()
    assert data["error"]["code"] == "unsupported_input_block"


def test_openapi_responses_schema(test_client):
    response = test_client.get("/openapi.json")
    assert response.status_code == 200

    schema = response.json()
    assert "/v1/responses" in schema["paths"]
    assert "ResponsesCreateRequest" in schema["components"]["schemas"]
    assert "ResponsesResponse" in schema["components"]["schemas"]
