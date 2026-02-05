"""Shared test model selection helpers."""

import os

from claude_code_api.models.claude import get_available_models, get_default_model


def get_test_model_id() -> str:
    test_model_id = os.getenv("CLAUDE_CODE_API_TEST_MODEL") or ""
    available = {model.id for model in get_available_models()}
    if test_model_id and test_model_id in available:
        return test_model_id
    return get_default_model()
