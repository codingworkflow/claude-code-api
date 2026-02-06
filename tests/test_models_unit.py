"""Unit tests for Claude model configuration and fallback behavior."""

import json

import pytest

from claude_code_api.models import claude as claude_models


@pytest.fixture(autouse=True)
def clear_models_cache():
    claude_models._load_models_config.cache_clear()
    yield
    claude_models._load_models_config.cache_clear()


def test_opus_46_is_available():
    available_models = {model.id for model in claude_models.get_available_models()}
    assert "claude-opus-4-6-20260205" in available_models


def test_opus_alias_resolves_to_canonical_model():
    assert (
        claude_models.validate_claude_model("claude-opus-4-6")
        == "claude-opus-4-6-20260205"
    )
    assert claude_models.validate_claude_model("opus") == "claude-opus-4-6-20260205"


def test_opus_45_falls_forward_to_latest_opus_when_missing(tmp_path, monkeypatch):
    custom_models_path = tmp_path / "models.json"
    custom_models_path.write_text(
        json.dumps(
            {
                "default_model": "claude-sonnet-4-5-20250929",
                "models": [
                    {
                        "id": "claude-opus-4-6-20260205",
                        "name": "Claude Opus 4.6",
                        "description": "Latest Opus",
                        "max_tokens": 65536,
                        "input_cost_per_1k": 0.005,
                        "output_cost_per_1k": 0.025,
                        "supports_streaming": True,
                        "supports_tools": True,
                    },
                    {
                        "id": "claude-sonnet-4-5-20250929",
                        "name": "Claude Sonnet 4.5",
                        "description": "Default Sonnet",
                        "max_tokens": 65536,
                        "input_cost_per_1k": 0.003,
                        "output_cost_per_1k": 0.015,
                        "supports_streaming": True,
                        "supports_tools": True,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv(claude_models.MODELS_CONFIG_ENV, str(custom_models_path))
    claude_models._load_models_config.cache_clear()

    assert (
        claude_models.validate_claude_model("claude-opus-4-5-20251101")
        == "claude-opus-4-6-20260205"
    )


def test_unknown_model_still_falls_back_to_default():
    assert (
        claude_models.validate_claude_model("totally-unknown-model")
        == claude_models.get_default_model()
    )
