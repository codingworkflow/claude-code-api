"""Pytest configuration and fixtures."""

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from httpx import AsyncClient

# Add the project root to Python path for imports
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from claude_code_api.core.config import settings

# Now import the app and configuration
from claude_code_api.main import app
from tests.model_utils import get_test_model_id


@pytest.fixture(scope="session", autouse=True)
def setup_test_environment():
    """Setup test environment before all tests."""
    # Create temporary directory for testing
    test_root = PROJECT_ROOT / "dist" / "tests"
    test_root.mkdir(parents=True, exist_ok=True)
    temp_dir = tempfile.mkdtemp(prefix="claude_api_test_", dir=str(test_root))

    # Store original settings
    original_settings = {
        "project_root": getattr(settings, "project_root", None),
        "require_auth": getattr(settings, "require_auth", False),
        "claude_binary_path": getattr(settings, "claude_binary_path", "claude"),
        "database_url": getattr(settings, "database_url", "sqlite:///./test.db"),
        "debug": getattr(settings, "debug", False),
    }

    # Set test settings
    settings.project_root = os.path.join(temp_dir, "projects")
    settings.require_auth = False

    # Prefer deterministic fixtures unless explicitly using real Claude
    use_real_claude = os.environ.get("CLAUDE_CODE_API_USE_REAL_CLAUDE") == "1"
    if not use_real_claude:
        fixtures_dir = Path(__file__).parent / "fixtures"
        index_path = fixtures_dir / "index.json"
        default_fixture = fixtures_dir / "claude_stream_simple.jsonl"

        fixture_rules = []
        if index_path.exists():
            try:
                fixture_rules = json.loads(index_path.read_text(encoding="utf-8"))
            except Exception as exc:
                raise RuntimeError(f"Failed to parse fixture index: {exc}") from exc

        # Create a mock binary that replays recorded JSONL fixtures
        mock_path = os.path.join(temp_dir, "claude")
        with open(mock_path, "w") as f:
            f.write("#!/usr/bin/env bash\n")
            f.write(
                'if [ "$1" == "--version" ]; then echo "Claude Code 1.0.0"; exit 0; fi\n'
            )
            f.write('prompt=""\n')
            f.write('args=("$@")\n')
            f.write("for ((i=0; i<${#args[@]}; i++)); do\n")
            f.write('  if [ "${args[$i]}" == "-p" ]; then\n')
            f.write('    prompt="${args[$((i+1))]}"\n')
            f.write("    break\n")
            f.write("  fi\n")
            f.write("done\n")
            f.write(
                'prompt_lower="$(printf "%s" "$prompt" | tr "[:upper:]" "[:lower:]")"\n'
            )
            f.write(f'fixture_default="{default_fixture}"\n')
            f.write('fixture_match="$fixture_default"\n')
            for rule in fixture_rules:
                matches = rule.get("match", [])
                fixture_file = rule.get("file")
                if not fixture_file or not matches:
                    continue
                fixture_path = fixtures_dir / fixture_file
                for match in matches:
                    match_escaped = str(match).replace('"', '\\"')
                    line = (
                        f'if echo "$prompt_lower" | grep -q "{match_escaped}"; '
                        f'then fixture_match="{fixture_path}"; '
                        "fi\n"
                    )
                    f.write(line)
            f.write('cat "$fixture_match"\n')
        os.chmod(mock_path, 0o755)
        settings.claude_binary_path = mock_path
    else:
        # Ensure the real binary is available when requested
        if not shutil.which(settings.claude_binary_path) and not os.path.exists(
            settings.claude_binary_path
        ):
            raise RuntimeError(
                f"CLAUDE_CODE_API_USE_REAL_CLAUDE=1 but binary not found at {settings.claude_binary_path}"
            )

    settings.database_url = f"sqlite:///{temp_dir}/test.db"
    settings.debug = True

    # Create directories
    os.makedirs(settings.project_root, exist_ok=True)

    yield temp_dir

    # Cleanup
    try:
        shutil.rmtree(temp_dir)
    except Exception as e:
        print(f"Cleanup warning: {e}")

    # Restore original settings (if they existed)
    for key, value in original_settings.items():
        if value is not None:
            setattr(settings, key, value)


@pytest.fixture
def test_client():
    """Create a test client for the FastAPI app."""
    with TestClient(app) as client:
        yield client


@pytest.fixture
async def async_test_client():
    """Create an async test client."""
    async with AsyncClient(app=app, base_url="http://test") as client:
        yield client


@pytest.fixture
def sample_chat_request():
    """Sample chat completion request."""
    return {
        "model": get_test_model_id(),
        "messages": [{"role": "user", "content": "Hi"}],
        "stream": False,
    }


@pytest.fixture
def sample_streaming_request():
    """Sample streaming chat completion request."""
    return {
        "model": get_test_model_id(),
        "messages": [{"role": "user", "content": "Tell me a joke"}],
        "stream": True,
    }


@pytest.fixture
def sample_project_request():
    """Sample project creation request."""
    return {"name": "Test Project", "description": "A test project"}


@pytest.fixture
def sample_session_request():
    """Sample session creation request."""
    return {
        "project_id": "test-project",
        "title": "Test Session",
        "model": get_test_model_id(),
    }


# Configure pytest
def pytest_configure(config):
    """Configure pytest."""
    config.addinivalue_line(
        "markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')"
    )
    config.addinivalue_line("markers", "integration: marks tests as integration tests")
    config.addinivalue_line("markers", "unit: marks tests as unit tests")
    config.addinivalue_line("markers", "e2e: marks tests as end-to-end tests")


def pytest_collection_modifyitems(config, items):
    """Modify test collection."""
    # Add markers based on test names/paths
    for item in items:
        if "integration" in item.nodeid:
            item.add_marker(pytest.mark.integration)
        elif "unit" in item.nodeid:
            item.add_marker(pytest.mark.unit)

        # Mark slow tests
        if any(
            keyword in item.name.lower()
            for keyword in ["concurrent", "performance", "large"]
        ):
            item.add_marker(pytest.mark.slow)
