"""Unit tests for Claude manager helpers."""

import os

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
