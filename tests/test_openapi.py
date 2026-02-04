"""OpenAPI schema checks for streaming and tool calls."""


def test_openapi_chat_completions_schema(test_client):
    response = test_client.get("/openapi.json")
    assert response.status_code == 200

    schema = response.json()
    assert "/v1/chat/completions" in schema["paths"]

    chat_post = schema["paths"]["/v1/chat/completions"]["post"]
    assert "requestBody" in chat_post

    content = chat_post["responses"]["200"]["content"]
    assert "application/json" in content
    assert "text/event-stream" in content

    components = schema.get("components", {}).get("schemas", {})
    assert "ChatMessage" in components
    assert "tool_calls" in components["ChatMessage"]["properties"]
    assert "ChatCompletionChunkDelta" in components
    assert "tool_calls" in components["ChatCompletionChunkDelta"]["properties"]
