"""Shared test model selection helpers."""

import os

from claude_code_api.models.claude import get_available_models, get_default_model

TEST_MODEL_ID = os.getenv("CLAUDE_CODE_API_TEST_MODEL", "claude-haiku-4-5-20250929")


def get_test_model_id() -> str:
    available = {model.id for model in get_available_models()}
    if TEST_MODEL_ID in available:
        return TEST_MODEL_ID
    return get_default_model()
