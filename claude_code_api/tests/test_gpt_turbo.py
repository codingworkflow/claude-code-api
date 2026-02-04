"""Tests for GPT-3.5 Turbo integration."""

import os

import pytest
from openai import OpenAI

from claude_code_api.models.openai import ChatCompletionRequest, ChatMessage

# Note: This test requires setting the OPENAI_API_KEY environment variable
# You can set this by running: export OPENAI_API_KEY='your-api-key-here'


@pytest.mark.skipif(
    not os.environ.get("OPENAI_API_KEY"),
    reason="OpenAI API key is not set. Set OPENAI_API_KEY environment variable to run this test.",
)
def test_gpt_turbo_prompt():
    """Test basic prompt with GPT-3.5 Turbo."""
    # You'll need to replace this with your actual OpenAI API key
    client = OpenAI(api_key="your-openai-api-key")

    # Create a test request that matches the OpenAI API structure
    messages = [
        {"role": "system", "content": "You are a helpful coding assistant."},
        {
            "role": "user",
            "content": "Write a Python function to calculate the factorial of a number.",
        },
    ]

    # Make the API call
    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=messages,
        temperature=0,  # For deterministic output
        max_tokens=250,  # Limit response length
    )

    # Validate the response
    assert response.choices[0].message.role == "assistant"
    assert response.choices[0].message.content is not None

    # Optional: Check the function content
    function_code = response.choices[0].message.content
    assert "def factorial" in function_code or "def fact" in function_code
    assert "return" in function_code


def test_claude_gpt_turbo_compatibility():
    """Ensure our models can parse GPT-3.5 Turbo request."""
    # Create a request matching GPT-3.5 Turbo structure
    request_data = {
        "model": "gpt-3.5-turbo",
        "messages": [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Hello, world!"},
        ],
        "temperature": 0.7,
        "max_tokens": 100,
        "stream": False,
    }

    # Try parsing with our models
    request = ChatCompletionRequest(**request_data)

    # Validate parsed request
    assert request.model == "gpt-3.5-turbo"
    assert len(request.messages) == 2
    assert all(isinstance(msg, ChatMessage) for msg in request.messages)
    assert request.temperature == 0.7
    assert request.max_tokens == 100
    assert not request.stream
