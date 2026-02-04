"""Tests for configuration helpers."""

import glob
import os
import subprocess

from claude_code_api.core import config as config_module


def test_find_claude_binary_env(monkeypatch, tmp_path):
    fake = tmp_path / "claude"
    fake.write_text("bin")
    monkeypatch.setenv("CLAUDE_BINARY_PATH", str(fake))
    assert config_module.find_claude_binary() == str(fake)


def test_find_claude_binary_shutil(monkeypatch):
    monkeypatch.delenv("CLAUDE_BINARY_PATH", raising=False)
    monkeypatch.setattr(
        config_module.shutil, "which", lambda _name: "/usr/local/bin/claude"
    )
    assert config_module.find_claude_binary() == "/usr/local/bin/claude"


def test_find_claude_binary_npm(monkeypatch, tmp_path):
    monkeypatch.delenv("CLAUDE_BINARY_PATH", raising=False)
    monkeypatch.setattr(config_module.shutil, "which", lambda _name: None)

    npm_bin = tmp_path / "bin"
    npm_bin.mkdir()
    (npm_bin / "claude").write_text("bin")

    class Result:
        returncode = 0
        stdout = str(npm_bin)

    monkeypatch.setattr(subprocess, "run", lambda *_a, **_k: Result())
    assert config_module.find_claude_binary() == str(npm_bin / "claude")


def test_find_claude_binary_glob(monkeypatch):
    monkeypatch.delenv("CLAUDE_BINARY_PATH", raising=False)
    monkeypatch.setattr(config_module.shutil, "which", lambda _name: None)
    monkeypatch.setattr(
        subprocess, "run", lambda *_a, **_k: (_ for _ in ()).throw(OSError("no"))
    )
    monkeypatch.setattr(glob, "glob", lambda _pattern: ["/a/claude", "/b/claude"])
    assert config_module.find_claude_binary() == "/b/claude"


def test_find_claude_binary_fallback(monkeypatch):
    monkeypatch.delenv("CLAUDE_BINARY_PATH", raising=False)
    monkeypatch.setattr(config_module.shutil, "which", lambda _name: None)
    monkeypatch.setattr(
        subprocess, "run", lambda *_a, **_k: (_ for _ in ()).throw(OSError("no"))
    )
    monkeypatch.setattr(glob, "glob", lambda _pattern: [])
    assert config_module.find_claude_binary() == "claude"


def test_looks_like_dotenv(tmp_path):
    good = tmp_path / "good.env"
    good.write_text("KEY=VALUE\n")
    assert config_module._looks_like_dotenv(str(good)) is True

    export = tmp_path / "export.env"
    export.write_text("export KEY=VALUE\n")
    assert config_module._looks_like_dotenv(str(export)) is True

    bad = tmp_path / "bad.env"
    bad.write_text("#!/bin/bash\necho nope\n")
    assert config_module._looks_like_dotenv(str(bad)) is False

    bad2 = tmp_path / "bad2.env"
    bad2.write_text("if [ 1 = 1 ]; then\n")
    assert config_module._looks_like_dotenv(str(bad2)) is False


def test_looks_like_dotenv_missing_file():
    assert config_module._looks_like_dotenv("/tmp/does-not-exist.env") is False


def test_shell_script_line_detection():
    assert config_module._is_shell_script_line("if something") is True
    assert config_module._is_shell_script_line("BASH_SOURCE") is True


def test_resolve_env_file(monkeypatch, tmp_path):
    monkeypatch.delenv("CLAUDE_CODE_API_ENV_FILE", raising=False)
    cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
        env_path = tmp_path / ".env"
        env_path.write_text("KEY=VALUE\n")
        assert config_module._resolve_env_file() == ".env"
    finally:
        os.chdir(cwd)

    monkeypatch.setenv("CLAUDE_CODE_API_ENV_FILE", "/tmp/explicit.env")
    assert config_module._resolve_env_file() == "/tmp/explicit.env"


def test_settings_parsers():
    settings = config_module.Settings()
    assert settings.parse_api_keys("a, b ,") == ["a", "b"]
    assert settings.parse_cors_lists("x,y") == ["x", "y"]
