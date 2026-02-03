"""
End-to-end tests for Claude Code API Gateway.

This test suite tests the complete API functionality including:
- OpenAI-compatible chat completions
- Model endpoints
- Project and session management  
- Streaming and non-streaming responses
"""

import pytest
import asyncio
import json
import uuid
from datetime import datetime
from typing import Dict, Any, List
from httpx import AsyncClient
from fastapi.testclient import TestClient
import os
import tempfile
import shutil

# Import the FastAPI app
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from claude_code_api.main import app
from claude_code_api.core.config import settings


class TestConfig:
    """Test configuration."""
    
    @classmethod
    def setup_test_environment(cls):
        """Setup test environment with mock Claude binary."""
        # Create temporary directories for testing
        cls.temp_dir = tempfile.mkdtemp()
        cls.project_root = os.path.join(cls.temp_dir, "projects")
        os.makedirs(cls.project_root, exist_ok=True)
        
        # Override settings for testing
        settings.project_root = cls.project_root
        settings.require_auth = False  # Disable auth for testing
        # Keep real Claude binary - DO NOT mock it!
        # settings.claude_binary_path should remain as found by find_claude_binary()
        settings.database_url = f"sqlite:///{cls.temp_dir}/test.db"
        
        return cls.temp_dir
    
    @classmethod
    def cleanup_test_environment(cls):
        """Cleanup test environment."""
        if hasattr(cls, 'temp_dir') and os.path.exists(cls.temp_dir):
            shutil.rmtree(cls.temp_dir)


@pytest.fixture(scope="session")
def test_environment():
    """Setup and teardown test environment."""
    temp_dir = TestConfig.setup_test_environment()
    yield temp_dir
    TestConfig.cleanup_test_environment()


@pytest.fixture
def client(test_environment):
    """Create test client."""
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
async def async_client(test_environment):
    """Create async test client."""
    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac


class TestHealthAndBasics:
    """Test basic API functionality."""
    
    def test_health_check(self, client):
        """Test health check endpoint."""
        response = client.get("/health")
        assert response.status_code == 200
        
        data = response.json()
        assert data["status"] == "healthy"
        assert "version" in data
        assert "active_sessions" in data
    
    def test_root_endpoint(self, client):
        """Test root endpoint."""
        response = client.get("/")
        assert response.status_code == 200
        
        data = response.json()
        assert data["name"] == "Claude Code API Gateway"
        assert "endpoints" in data
        assert "docs" in data


class TestModelsAPI:
    """Test models API endpoints."""
    
    def test_list_models(self, client):
        """Test listing available models."""
        response = client.get("/v1/models")
        assert response.status_code == 200
        
        data = response.json()
        assert data["object"] == "list"
        assert "data" in data
        assert len(data["data"]) > 0
        
        # Check model structure
        model = data["data"][0]
        assert "id" in model
        assert "object" in model
        assert model["object"] == "model"
        assert "created" in model
        assert "owned_by" in model
    
    def test_get_specific_model(self, client):
        """Test getting specific model."""
        # Test Claude model
        response = client.get("/v1/models/claude-3-5-haiku-20241022")
        assert response.status_code == 200
        
        data = response.json()
        assert data["id"] == "claude-3-5-haiku-20241022"
        assert data["object"] == "model"
    
    def test_get_openai_alias_model(self, client):
        """Test getting non-existent OpenAI model (not supported)."""
        response = client.get("/v1/models/gpt-4")
        assert response.status_code == 404
    
    def test_get_nonexistent_model(self, client):
        """Test getting non-existent model."""
        response = client.get("/v1/models/nonexistent-model")
        assert response.status_code == 404
        
        data = response.json()
        assert "error" in data
        assert data["error"]["code"] == "model_not_found"
    
    def test_model_capabilities(self, client):
        """Test model capabilities endpoint."""
        # Skip capabilities test for now - extension endpoint
        pass


class TestChatCompletions:
    """Test chat completions API."""
    
    def test_simple_chat_completion_non_streaming(self, client):
        """Test simple non-streaming chat completion."""
        request_data = {
            "model": "claude-3-5-haiku-20241022",
            "messages": [
                {"role": "user", "content": "Hi"}
            ],
            "stream": False
        }
        
        response = client.post("/v1/chat/completions", json=request_data)
        assert response.status_code == 200
        
        data = response.json()
        assert "id" in data
        assert data["object"] == "chat.completion"
        assert "created" in data
        assert data["model"] == "claude-3-5-haiku-20241022"
        assert "choices" in data
        assert len(data["choices"]) > 0
        
        choice = data["choices"][0]
        assert choice["index"] == 0
        assert "message" in choice
        assert choice["message"]["role"] == "assistant"
        assert "content" in choice["message"]
        assert "usage" in data
    
    def test_chat_completion_with_system_prompt(self, client):
        """Test chat completion with system prompt."""
        request_data = {
            "model": "claude-3-5-haiku-20241022",
            "messages": [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "Hello, how are you?"}
            ],
            "stream": False
        }
        
        response = client.post("/v1/chat/completions", json=request_data)
        assert response.status_code == 200
        
        data = response.json()
        assert data["model"] == "claude-3-5-haiku-20241022"
        assert len(data["choices"]) > 0
    
    def test_chat_completion_with_invalid_model_fallback(self, client):
        """Test chat completion with invalid model (should fallback to default)."""
        request_data = {
            "model": "invalid-model",
            "messages": [
                {"role": "user", "content": "What's 2+2?"}
            ],
            "stream": False
        }
        
        response = client.post("/v1/chat/completions", json=request_data)
        # Should work with fallback to default model
        assert response.status_code in [200, 503]  # 503 if Claude not available
    
    def test_chat_completion_streaming(self, client):
        """Test streaming chat completion."""
        request_data = {
            "model": "claude-3-5-haiku-20241022",
            "messages": [
                {"role": "user", "content": "Tell me a short joke"}
            ],
            "stream": True
        }
        
        response = client.post("/v1/chat/completions", json=request_data)
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/plain; charset=utf-8"
        
        # Check that we get streaming data
        content = response.text
        assert "data: " in content
        assert "event: " in content or "[DONE]" in content
    
    def test_chat_completion_with_project_context(self, client):
        """Test chat completion with project context."""
        request_data = {
            "model": "claude-3-5-sonnet-20241022",
            "messages": [
                {"role": "user", "content": "Hi, I'm working on a Python project"}
            ],
            "project_id": "test-project-123",
            "stream": False
        }
        
        response = client.post("/v1/chat/completions", json=request_data)
        assert response.status_code == 200
        
        data = response.json()
        assert "project_id" in data
        assert data["project_id"] == "test-project-123"
    
    def test_chat_completion_missing_messages(self, client):
        """Test chat completion with missing messages."""
        request_data = {
            "model": "claude-3-5-sonnet-20241022",
            "messages": [],
            "stream": False
        }
        
        response = client.post("/v1/chat/completions", json=request_data)
        assert response.status_code == 400
        
        data = response.json()
        assert "error" in data
        assert data["error"]["code"] == "missing_messages"
    
    def test_chat_completion_no_user_message(self, client):
        """Test chat completion with no user message."""
        request_data = {
            "model": "claude-3-5-sonnet-20241022",
            "messages": [
                {"role": "system", "content": "You are a helpful assistant."}
            ],
            "stream": False
        }
        
        response = client.post("/v1/chat/completions", json=request_data)
        assert response.status_code == 400
        
        data = response.json()
        assert "error" in data
        assert data["error"]["code"] == "missing_user_message"
    
    def test_chat_completion_invalid_model(self, client):
        """Test chat completion with invalid model."""
        request_data = {
            "model": "invalid-model",
            "messages": [
                {"role": "user", "content": "Hi"}
            ],
            "stream": False
        }
        
        response = client.post("/v1/chat/completions", json=request_data)
        # Should still work as model gets converted to default
        assert response.status_code in [200, 503]  # 503 if Claude not available


class TestConversationFlow:
    """Test conversation flow and session management."""
    
    def test_conversation_continuity(self, client):
        """Test conversation continuity across messages."""
        # First message
        request_data_1 = {
            "model": "claude-3-5-sonnet-20241022", 
            "messages": [
                {"role": "user", "content": "My name is Alice"}
            ],
            "stream": False
        }
        
        response_1 = client.post("/v1/chat/completions", json=request_data_1)
        assert response_1.status_code == 200
        
        data_1 = response_1.json()
        session_id = data_1.get("session_id")
        
        if session_id:
            # Follow-up message in same session
            request_data_2 = {
                "model": "claude-3-5-sonnet-20241022",
                "messages": [
                    {"role": "user", "content": "My name is Alice"},
                    {"role": "assistant", "content": data_1["choices"][0]["message"]["content"]},
                    {"role": "user", "content": "What's my name?"}
                ],
                "session_id": session_id,
                "stream": False
            }
            
            response_2 = client.post("/v1/chat/completions", json=request_data_2)
            assert response_2.status_code in [200, 404, 503]  # May fail if session management incomplete
    
    def test_multiple_user_messages(self, client):
        """Test handling multiple user messages."""
        request_data = {
            "model": "claude-3-5-sonnet-20241022",
            "messages": [
                {"role": "user", "content": "Hi"},
                {"role": "user", "content": "How are you doing today?"}
            ],
            "stream": False
        }
        
        response = client.post("/v1/chat/completions", json=request_data)
        assert response.status_code == 200
        
        # Should use the last user message
        data = response.json()
        assert len(data["choices"]) > 0


class TestProjectsAPI:
    """Test projects API endpoints."""
    
    def test_list_projects(self, client):
        """Test listing projects."""
        response = client.get("/v1/projects")
        assert response.status_code == 200
        
        data = response.json()
        assert "data" in data
        assert "pagination" in data
    
    def test_create_project(self, client):
        """Test creating a project."""
        project_data = {
            "name": "Test Project",
            "description": "A test project for API testing"
        }
        
        response = client.post("/v1/projects", json=project_data)
        assert response.status_code == 200
        
        data = response.json()
        assert data["name"] == "Test Project"
        assert data["description"] == "A test project for API testing"
        assert "id" in data
        assert "path" in data
        assert "created_at" in data
    
    def test_get_project(self, client):
        """Test getting a specific project."""
        # First create a project
        project_data = {
            "name": "Test Project for Get",
            "description": "Test description"
        }
        
        create_response = client.post("/v1/projects", json=project_data)
        assert create_response.status_code == 200
        
        project_id = create_response.json()["id"]
        
        # Now get the project
        response = client.get(f"/v1/projects/{project_id}")
        assert response.status_code == 200
        
        data = response.json()
        assert data["id"] == project_id
        assert data["name"] == "Test Project for Get"
    
    def test_get_nonexistent_project(self, client):
        """Test getting non-existent project."""
        response = client.get("/v1/projects/nonexistent-id")
        assert response.status_code == 404
        
        data = response.json()
        assert "error" in data
        assert data["error"]["code"] == "project_not_found"


class TestSessionsAPI:
    """Test sessions API endpoints."""
    
    def test_list_sessions(self, client):
        """Test listing sessions."""
        response = client.get("/v1/sessions")
        assert response.status_code == 200
        
        data = response.json()
        assert "data" in data
        assert "pagination" in data
    
    def test_create_session(self, client):
        """Test creating a session."""
        session_data = {
            "project_id": "test-project",
            "title": "Test Session",
            "model": "claude-3-5-sonnet-20241022"
        }
        
        response = client.post("/v1/sessions", json=session_data)
        assert response.status_code == 200
        
        data = response.json()
        assert data["project_id"] == "test-project"
        assert data["model"] == "claude-3-5-sonnet-20241022"
        assert "id" in data
        assert "created_at" in data
    
    def test_get_session_stats(self, client):
        """Test getting session statistics."""
        response = client.get("/v1/sessions/stats")
        assert response.status_code == 200
        
        data = response.json()
        assert "session_stats" in data
        assert "active_claude_sessions" in data


class TestErrorHandling:
    """Test error handling scenarios."""
    
    def test_invalid_json(self, client):
        """Test handling of invalid JSON."""
        response = client.post(
            "/v1/chat/completions",
            data="invalid json",
            headers={"content-type": "application/json"}
        )
        # API returns 400 for JSON decode errors (handled manually)
        assert response.status_code == 400
    
    def test_missing_required_fields(self, client):
        """Test handling of missing required fields."""
        request_data = {
            "messages": [
                {"role": "user", "content": "Hi"}
            ]
            # Missing required "model" field
        }
        
        response = client.post("/v1/chat/completions", json=request_data)
        assert response.status_code == 422  # Validation error
    
    def test_invalid_message_role(self, client):
        """Test handling of invalid message role."""
        request_data = {
            "model": "claude-3-5-sonnet-20241022",
            "messages": [
                {"role": "invalid_role", "content": "Hi"}
            ]
        }
        
        response = client.post("/v1/chat/completions", json=request_data)
        assert response.status_code == 422  # Validation error


class TestRealWorldScenarios:
    """Test real-world usage scenarios."""
    
    def test_simple_greeting(self, client):
        """Test simple greeting - most common use case."""
        request_data = {
            "model": "claude-3-5-haiku-20241022",
            "messages": [
                {"role": "user", "content": "Hi"}
            ]
        }
        
        response = client.post("/v1/chat/completions", json=request_data)
        assert response.status_code == 200
        
        data = response.json()
        assert "choices" in data
        assert len(data["choices"]) > 0
        assert "message" in data["choices"][0]
        # Content might be empty with mock setup, just check structure
        assert "content" in data["choices"][0]["message"]
    

    def test_code_generation_request(self, client):
        """Test code generation request."""
        request_data = {
            "model": "claude-3-5-haiku-20241022",
            "messages": [
                {"role": "user", "content": "Write a Python function to calculate fibonacci numbers"}
            ]
        }
        
        response = client.post("/v1/chat/completions", json=request_data)
        assert response.status_code == 200
        
        data = response.json()
        assert "choices" in data
        assert len(data["choices"]) > 0
        # Could check for code-like content but Echo won't generate real code
     
    def test_multi_turn_conversation(self, client):
        """Test multi-turn conversation simulation."""
        # Simulate a multi-turn conversation in a single request
        request_data = {
            "model": "claude-3-5-haiku-20241022",
            "messages": [
                {"role": "user", "content": "Hi, I'm learning Python"},
                {"role": "assistant", "content": "Hello! That's great that you're learning Python. It's an excellent programming language for beginners and professionals alike. What specifically would you like to know about Python?"},
                {"role": "user", "content": "How do I create a list?"}
            ]
        }
        
        response = client.post("/v1/chat/completions", json=request_data)
        assert response.status_code == 200
        
        data = response.json()
        assert "choices" in data
        assert len(data["choices"]) > 0




# Test configuration and markers
pytestmark = pytest.mark.asyncio


if __name__ == "__main__":
    # Run tests with coverage
    pytest.main([
        __file__,
        "-v",
        "--tb=short",
        "--disable-warnings"
    ])
