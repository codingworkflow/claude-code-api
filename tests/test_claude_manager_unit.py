"""Unit tests for Claude manager helpers."""

import os
import types

import pytest

from claude_code_api.core import claude_manager as cm
from claude_code_api.core.config import settings


def test_create_and_cleanup_project_directory(tmp_path):
    original_root = settings.project_root
    try:
        settings.project_root = str(tmp_path)
        project_path = cm.create_project_directory("proj1")
        assert os.path.isdir(project_path)
        cm.cleanup_project_directory(project_path)
        assert not os.path.exists(project_path)
    finally:
        settings.project_root = original_root


def test_validate_claude_binary(monkeypatch):
    class Result:
        def __init__(self, returncode):
            self.returncode = returncode

    def fake_run(*_args, **_kwargs):
        return Result(0)

    monkeypatch.setattr(cm.subprocess, "run", fake_run)
    assert cm.validate_claude_binary() is True

    def fake_run_fail(*_args, **_kwargs):
        raise OSError("nope")

    monkeypatch.setattr(cm.subprocess, "run", fake_run_fail)
    assert cm.validate_claude_binary() is False


def test_decode_output_line():
    process = cm.ClaudeProcess(session_id="sess", project_path="/tmp")
    data = process._decode_output_line(b'{"type":"assistant"}\n')
    assert data["type"] == "assistant"

    data = process._decode_output_line(b'data: {"type":"assistant"}\n')
    assert data["type"] == "assistant"

    data = process._decode_output_line(b"not-json\n")
    assert data["type"] == "text"


@pytest.mark.asyncio
async def test_create_session_rejects_duplicate_active_session(monkeypatch, tmp_path):
    manager = cm.ClaudeManager()

    async def fake_start(self, prompt, model=None, system_prompt=None):
        self.is_running = True
        return True

    monkeypatch.setattr(cm.ClaudeProcess, "start", fake_start)

    await manager.create_session(
        session_id="sess-dup",
        project_path=str(tmp_path),
        prompt="first prompt",
        model="claude-sonnet-4-5-20250929",
    )

    with pytest.raises(cm.ClaudeSessionConflictError):
        await manager.create_session(
            session_id="sess-dup",
            project_path=str(tmp_path),
            prompt="second prompt",
            model="claude-sonnet-4-5-20250929",
        )

    await manager.cleanup_all()


@pytest.mark.asyncio
async def test_create_session_replaces_stale_process(monkeypatch, tmp_path):
    manager = cm.ClaudeManager()

    async def fake_start(self, prompt, model=None, system_prompt=None):
        self.is_running = True
        return True

    monkeypatch.setattr(cm.ClaudeProcess, "start", fake_start)

    first_process = await manager.create_session(
        session_id="sess-stale",
        project_path=str(tmp_path),
        prompt="first prompt",
        model="claude-sonnet-4-5-20250929",
    )
    first_process.is_running = False

    second_process = await manager.create_session(
        session_id="sess-stale",
        project_path=str(tmp_path),
        prompt="second prompt",
        model="claude-sonnet-4-5-20250929",
    )

    assert second_process is not first_process
    assert manager.get_session("sess-stale") is second_process

    await manager.cleanup_all()


@pytest.mark.asyncio
async def test_create_session_retries_opus_45_when_opus_46_rejected(
    monkeypatch, tmp_path
):
    manager = cm.ClaudeManager()
    attempted_models = []

    monkeypatch.setattr(
        cm,
        "get_available_models",
        lambda: [
            types.SimpleNamespace(id="claude-opus-4-5-20251101"),
            types.SimpleNamespace(id="claude-opus-4-6-20260205"),
        ],
    )

    async def fake_start(self, prompt, model=None, system_prompt=None):
        attempted_models.append(model)
        if model == "claude-opus-4-6-20260205":
            self.last_error = "invalid model: claude-opus-4-6-20260205"
            self.is_running = False
            return False
        self.is_running = True
        return True

    monkeypatch.setattr(cm.ClaudeProcess, "start", fake_start)

    process = await manager.create_session(
        session_id="sess-fallback",
        project_path=str(tmp_path),
        prompt="prompt",
        model="claude-opus-4-6-20260205",
    )

    assert process is not None
    assert attempted_models == [
        "claude-opus-4-6-20260205",
        "claude-opus-4-5-20251101",
    ]

    await manager.cleanup_all()


@pytest.mark.asyncio
async def test_create_session_raises_when_model_rejected_without_fallback(
    monkeypatch, tmp_path
):
    manager = cm.ClaudeManager()

    monkeypatch.setattr(
        cm,
        "get_available_models",
        lambda: [types.SimpleNamespace(id="claude-sonnet-4-5-20250929")],
    )

    async def fake_start(self, prompt, model=None, system_prompt=None):
        self.last_error = "unsupported model"
        self.is_running = False
        return False

    monkeypatch.setattr(cm.ClaudeProcess, "start", fake_start)

    with pytest.raises(cm.ClaudeModelNotSupportedError):
        await manager.create_session(
            session_id="sess-model-error",
            project_path=str(tmp_path),
            prompt="prompt",
            model="claude-opus-4-6-20260205",
        )

    await manager.cleanup_all()


@pytest.mark.asyncio
async def test_create_session_raises_for_non_model_start_failure_without_fallback(
    monkeypatch, tmp_path
):
    manager = cm.ClaudeManager()
    attempted_models = []

    monkeypatch.setattr(
        cm,
        "get_available_models",
        lambda: [types.SimpleNamespace(id="claude-opus-4-5-20251101")],
    )

    async def fake_start(self, prompt, model=None, system_prompt=None):
        attempted_models.append(model)
        self.last_error = "failed to spawn process"
        self.is_running = False
        return False

    monkeypatch.setattr(cm.ClaudeProcess, "start", fake_start)

    with pytest.raises(cm.ClaudeProcessStartError):
        await manager.create_session(
            session_id="sess-process-error",
            project_path=str(tmp_path),
            prompt="prompt",
            model="claude-opus-4-6-20260205",
        )

    assert attempted_models == ["claude-opus-4-6-20260205"]
    await manager.cleanup_all()


@pytest.mark.asyncio
async def test_create_session_without_model_does_not_force_model_flag(
    monkeypatch, tmp_path
):
    manager = cm.ClaudeManager()
    attempted_models = []

    async def fake_start(self, prompt, model=None, system_prompt=None):
        attempted_models.append(model)
        self.is_running = True
        return True

    monkeypatch.setattr(cm.ClaudeProcess, "start", fake_start)

    await manager.create_session(
        session_id="sess-no-model",
        project_path=str(tmp_path),
        prompt="prompt",
        model=None,
    )

    assert attempted_models == [None]

    await manager.cleanup_all()
