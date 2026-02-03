"""Pytest configuration and fixtures."""

import pytest
import os
import sys
import tempfile
import shutil
from pathlib import Path
from fastapi.testclient import TestClient
from httpx import AsyncClient

# Add the project root to Python path for imports
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Now import the app and configuration
from claude_code_api.main import app
from claude_code_api.core.config import settings


@pytest.fixture(scope="session", autouse=True)
def setup_test_environment():
    """Setup test environment before all tests."""
    # Create temporary directory for testing
    temp_dir = tempfile.mkdtemp(prefix="claude_api_test_")
    
    # Store original settings
    original_settings = {
        "project_root": getattr(settings, "project_root", None),
        "require_auth": getattr(settings, "require_auth", False),
        "claude_binary_path": getattr(settings, "claude_binary_path", "claude"),
        "database_url": getattr(settings, "database_url", "sqlite:///./test.db"),
        "debug": getattr(settings, "debug", False)
    }
    
    # Set test settings
    settings.project_root = os.path.join(temp_dir, "projects")
    settings.require_auth = False

    # Keep the real Claude binary path if it exists, otherwise use a mock
    # settings.claude_binary_path should remain as found by find_claude_binary()
    if not shutil.which(settings.claude_binary_path) and not os.path.exists(settings.claude_binary_path):
        # Create a mock binary for CI/Sandbox environments
        mock_path = os.path.join(temp_dir, "claude")
        with open(mock_path, "w") as f:
            f.write('#!/bin/bash\n')
            f.write('if [ "$1" == "--version" ]; then echo "Claude Code 1.0.0"; exit 0; fi\n')
            f.write('echo \'{"type":"message","message":{"role":"assistant","content":"Mock response"}}\'\n')
            f.write('echo \'{"type":"result","result":"done"}\'\n')
        os.chmod(mock_path, 0o755)
        settings.claude_binary_path = mock_path

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
        "model": "claude-3-5-sonnet-20241022",
        "messages": [
            {"role": "user", "content": "Hi"}
        ],
        "stream": False
    }


@pytest.fixture
def sample_streaming_request():
    """Sample streaming chat completion request."""
    return {
        "model": "claude-3-5-sonnet-20241022", 
        "messages": [
            {"role": "user", "content": "Tell me a joke"}
        ],
        "stream": True
    }


@pytest.fixture
def sample_project_request():
    """Sample project creation request."""
    return {
        "name": "Test Project",
        "description": "A test project"
    }


@pytest.fixture
def sample_session_request():
    """Sample session creation request."""
    return {
        "project_id": "test-project",
        "title": "Test Session",
        "model": "claude-3-5-sonnet-20241022"
    }


# Configure pytest
def pytest_configure(config):
    """Configure pytest."""
    config.addinivalue_line(
        "markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')"
    )
    config.addinivalue_line(
        "markers", "integration: marks tests as integration tests"
    )
    config.addinivalue_line(
        "markers", "unit: marks tests as unit tests"
    )


def pytest_collection_modifyitems(config, items):
    """Modify test collection."""
    # Add markers based on test names/paths
    for item in items:
        if "integration" in item.nodeid:
            item.add_marker(pytest.mark.integration)
        elif "unit" in item.nodeid:
            item.add_marker(pytest.mark.unit)
        
        # Mark slow tests
        if any(keyword in item.name.lower() for keyword in ["concurrent", "performance", "large"]):
            item.add_marker(pytest.mark.slow)
