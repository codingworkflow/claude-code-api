"""Configuration management for Claude Code API Gateway."""

import os
import shutil
from typing import List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def find_claude_binary() -> str:
    """Find Claude binary path automatically."""
    # First check environment variable
    if "CLAUDE_BINARY_PATH" in os.environ:
        claude_path = os.environ["CLAUDE_BINARY_PATH"]
        if os.path.exists(claude_path):
            return claude_path

    # Try to find claude in PATH - this should work for npm global installs
    claude_path = shutil.which("claude")
    if claude_path:
        return claude_path

    # Import npm environment if needed
    try:
        import subprocess

        # Try to get npm global bin path
        result = subprocess.run(["npm", "bin", "-g"], capture_output=True, text=True)
        if result.returncode == 0:
            npm_bin_path = result.stdout.strip()
            claude_npm_path = os.path.join(npm_bin_path, "claude")
            if os.path.exists(claude_npm_path):
                return claude_npm_path
    except Exception:
        pass

    # Fallback to common npm/nvm locations
    import glob

    common_patterns = [
        "/usr/local/bin/claude",
        "/usr/local/share/nvm/versions/node/*/bin/claude",
        "~/.nvm/versions/node/*/bin/claude",
    ]

    for pattern in common_patterns:
        expanded_pattern = os.path.expanduser(pattern)
        matches = glob.glob(expanded_pattern)
        if matches:
            # Return the most recent version
            return sorted(matches)[-1]

    return "claude"  # Final fallback


def default_project_root() -> str:
    """Default project root under the current working directory."""
    return os.path.join(os.getcwd(), "claude_projects")


def default_session_map_path() -> str:
    """Default path for CLI-to-API session mapping."""
    return os.path.join(os.getcwd(), "claude_sessions", "session_map.json")


def default_log_file_path() -> str:
    """Default path for application logs."""
    return os.path.join(os.getcwd(), "dist", "logs", "claude-code-api.log")


def _is_shell_script_line(line: str) -> bool:
    if not line:
        return False
    if line.startswith("#!") or line.startswith("set "):
        return True
    if "BASH_SOURCE" in line or "[[" in line:
        return True
    return line.startswith(("if ", "fi", "for ", "done", "source "))


def _strip_export_prefix(line: str) -> str:
    if line.startswith("export "):
        return line[len("export ") :].lstrip()
    return line


def _looks_like_dotenv(path: str) -> bool:
    """Return True when a file appears to be a simple KEY=VALUE dotenv file."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                if _is_shell_script_line(stripped):
                    return False
                stripped = _strip_export_prefix(stripped)
                return "=" in stripped
    except OSError:
        return False
    return True


def _resolve_env_file() -> str | None:
    """Pick a dotenv file only when it is likely compatible."""
    explicit = os.getenv("CLAUDE_CODE_API_ENV_FILE")
    if explicit:
        return explicit
    for candidate in (".env.local", ".env"):
        if os.path.exists(candidate) and _looks_like_dotenv(candidate):
            return candidate
    return None


class Settings(BaseSettings):
    """Application settings."""

    model_config = SettingsConfigDict(
        env_file=_resolve_env_file(),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # API Configuration
    api_title: str = "Claude Code API Gateway"
    api_version: str = "1.0.0"
    api_description: str = "OpenAI-compatible API for Claude Code"

    # Server Configuration
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False

    # Authentication
    api_keys: List[str] = Field(default_factory=list)
    require_auth: bool = False

    @field_validator("api_keys", mode="before")
    def parse_api_keys(cls, v):
        if isinstance(v, str):
            return [x.strip() for x in v.split(",") if x.strip()]
        return v or []

    # Claude Configuration
    claude_binary_path: str = find_claude_binary()
    claude_api_key: str = ""
    default_model: str = "claude-sonnet-4-5-20250929"
    max_concurrent_sessions: int = 10
    session_timeout_minutes: int = 30

    # Project Configuration
    project_root: str = default_project_root()
    max_project_size_mb: int = 1000
    cleanup_interval_minutes: int = 60
    session_map_path: str = default_session_map_path()

    # Database Configuration
    database_url: str = "sqlite:///./claude_api.db"

    # Logging Configuration
    log_level: str = "INFO"
    log_format: str = "json"
    log_file_path: str = default_log_file_path()
    log_to_file: bool = True
    log_max_bytes: int = 10 * 1024 * 1024
    log_backup_count: int = 5
    log_to_console: bool = True
    log_min_level_when_not_debug: str = "WARNING"

    # CORS Configuration
    allowed_origins: List[str] = Field(
        default=["http://localhost:8000", "http://127.0.0.1:8000"]
    )
    allowed_methods: List[str] = Field(
        default=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD", "PATCH"]
    )
    allowed_headers: List[str] = Field(default=["*"])

    @field_validator(
        "allowed_origins", "allowed_methods", "allowed_headers", mode="before"
    )
    def parse_cors_lists(cls, v):
        if isinstance(v, str):
            return [x.strip() for x in v.split(",") if x.strip()]
        return v

    # Rate Limiting
    rate_limit_requests_per_minute: int = 100
    rate_limit_burst: int = 10

    # Streaming Configuration
    streaming_chunk_size: int = 1024
    streaming_timeout_seconds: int = 300


# Create global settings instance
settings = Settings()

# Ensure project root exists
os.makedirs(settings.project_root, exist_ok=True)
