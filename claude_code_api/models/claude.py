"""Claude Code specific models and utilities."""

import json
import os
import re
from datetime import datetime
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field

from claude_code_api.utils.time import utc_now

SESSION_ID_DESC = "Session ID"
PROJECT_PATH_DESC = "Project path"


class ClaudeMessageType(str, Enum):
    """Claude message types from JSONL output."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    RESULT = "result"
    ERROR = "error"
    TOOL_USE = "tool_use"
    TOOL_RESULT = "tool_result"


class ClaudeToolType(str, Enum):
    """Claude Code built-in tools."""

    BASH = "bash"
    EDIT = "edit"
    READ = "read"
    WRITE = "write"
    LS = "ls"
    GREP = "grep"
    GLOB = "glob"
    TODO_WRITE = "todowrite"
    MULTI_EDIT = "multiedit"


class ClaudeMessage(BaseModel):
    """Claude message from JSONL output."""

    type: str = Field(..., description="Message type")
    subtype: Optional[str] = Field(None, description="Message subtype")
    message: Optional[Dict[str, Any]] = Field(None, description="Message content")
    session_id: Optional[str] = Field(None, description=SESSION_ID_DESC)
    model: Optional[str] = Field(None, description="Model used")
    cwd: Optional[str] = Field(None, description="Current working directory")
    tools: Optional[List[str]] = Field(None, description="Available tools")
    result: Optional[str] = Field(None, description="Execution result")
    error: Optional[str] = Field(None, description="Error message")
    usage: Optional[Dict[str, Any]] = Field(None, description="Token usage")
    cost_usd: Optional[float] = Field(None, description="Cost in USD")
    duration_ms: Optional[int] = Field(None, description="Duration in milliseconds")
    num_turns: Optional[int] = Field(None, description="Number of turns")
    timestamp: Optional[str] = Field(None, description="Timestamp")


class ClaudeToolUse(BaseModel):
    """Claude tool use information."""

    id: str = Field(..., description="Tool use ID")
    name: str = Field(..., description="Tool name")
    input: Dict[str, Any] = Field(..., description="Tool input parameters")


class ClaudeToolResult(BaseModel):
    """Claude tool result information."""

    tool_use_id: str = Field(..., description="Tool use ID")
    content: Union[str, Dict[str, Any]] = Field(..., description="Tool result content")
    is_error: Optional[bool] = Field(
        False, description="Whether this is an error result"
    )


def _default_model_factory() -> str:
    return get_default_model()


class ClaudeSessionInfo(BaseModel):
    """Claude session information."""

    session_id: str = Field(..., description=SESSION_ID_DESC)
    project_path: str = Field(..., description=PROJECT_PATH_DESC)
    model: str = Field(..., description="Model being used")
    started_at: datetime = Field(..., description="Session start time")
    is_running: bool = Field(..., description="Whether session is running")
    total_tokens: int = Field(0, description="Total tokens used")
    total_cost: float = Field(0.0, description="Total cost")
    message_count: int = Field(0, description="Number of messages")


class ClaudeProcessStatus(str, Enum):
    """Claude process status."""

    STARTING = "starting"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"
    TIMEOUT = "timeout"


class ClaudeExecutionRequest(BaseModel):
    """Claude execution request."""

    prompt: str = Field(..., description="User prompt")
    project_path: str = Field(..., description=PROJECT_PATH_DESC)
    model: Optional[str] = Field(None, description="Model to use")
    system_prompt: Optional[str] = Field(None, description="System prompt")
    resume_session: Optional[str] = Field(None, description="Session ID to resume")
    stream: bool = Field(True, description="Whether to stream output")


class ClaudeExecutionResponse(BaseModel):
    """Claude execution response."""

    session_id: str = Field(..., description=SESSION_ID_DESC)
    status: ClaudeProcessStatus = Field(..., description="Execution status")
    messages: List[ClaudeMessage] = Field(..., description="Messages from execution")
    total_tokens: int = Field(0, description="Total tokens used")
    total_cost: float = Field(0.0, description="Total cost")
    duration_ms: int = Field(0, description="Execution duration")


class ClaudeStreamingChunk(BaseModel):
    """Claude streaming chunk."""

    session_id: str = Field(..., description=SESSION_ID_DESC)
    chunk_type: str = Field(..., description="Type of chunk")
    data: ClaudeMessage = Field(..., description="Chunk data")
    is_final: bool = Field(False, description="Whether this is the final chunk")


class ClaudeProjectConfig(BaseModel):
    """Claude project configuration."""

    project_id: str = Field(..., description="Project ID")
    name: str = Field(..., description="Project name")
    path: str = Field(..., description=PROJECT_PATH_DESC)
    default_model: str = Field(
        default_factory=_default_model_factory, description="Default model"
    )
    system_prompt: Optional[str] = Field(None, description="Default system prompt")
    tools_enabled: List[ClaudeToolType] = Field(
        default_factory=list, description="Enabled tools"
    )
    max_tokens: Optional[int] = Field(None, description="Maximum tokens per request")
    temperature: Optional[float] = Field(None, description="Temperature setting")
    created_at: datetime = Field(default_factory=utc_now, description="Creation time")
    updated_at: datetime = Field(
        default_factory=utc_now, description="Last update time"
    )


class ClaudeFileInfo(BaseModel):
    """Claude file information."""

    path: str = Field(..., description="File path")
    name: str = Field(..., description="File name")
    size: int = Field(..., description="File size in bytes")
    modified_at: datetime = Field(..., description="Last modified time")
    is_directory: bool = Field(..., description="Whether this is a directory")
    extension: Optional[str] = Field(None, description="File extension")


class ClaudeWorkspaceInfo(BaseModel):
    """Claude workspace information."""

    path: str = Field(..., description="Workspace path")
    files: List[ClaudeFileInfo] = Field(..., description="Files in workspace")
    total_files: int = Field(..., description="Total number of files")
    total_size: int = Field(..., description="Total size in bytes")
    claude_md_files: List[str] = Field(..., description="CLAUDE.md files found")


class ClaudeVersionInfo(BaseModel):
    """Claude version information."""

    version: str = Field(..., description="Claude Code version")
    build: Optional[str] = Field(None, description="Build information")
    is_available: bool = Field(..., description="Whether Claude is available")
    path: str = Field(..., description="Path to Claude binary")


class ClaudeErrorInfo(BaseModel):
    """Claude error information."""

    error_type: str = Field(..., description="Type of error")
    message: str = Field(..., description="Error message")
    session_id: Optional[str] = Field(
        None, description="Session ID where error occurred"
    )
    timestamp: datetime = Field(default_factory=utc_now, description="Error timestamp")
    traceback: Optional[str] = Field(None, description="Error traceback")


class ClaudeMetrics(BaseModel):
    """Claude usage metrics."""

    total_sessions: int = Field(..., description="Total number of sessions")
    active_sessions: int = Field(..., description="Currently active sessions")
    total_tokens: int = Field(..., description="Total tokens processed")
    total_cost: float = Field(..., description="Total cost incurred")
    avg_session_duration_ms: float = Field(..., description="Average session duration")
    most_used_model: str = Field(..., description="Most frequently used model")
    tool_usage_stats: Dict[str, int] = Field(..., description="Tool usage statistics")
    error_rate: float = Field(..., description="Error rate percentage")


class ClaudeModelInfo(BaseModel):
    """Claude model information."""

    id: str = Field(..., description="Model ID")
    name: str = Field(..., description="Model display name")
    description: str = Field(..., description="Model description")
    max_tokens: int = Field(..., description="Maximum tokens supported")
    input_cost_per_1k: float = Field(..., description="Input cost per 1K tokens")
    output_cost_per_1k: float = Field(..., description="Output cost per 1K tokens")
    supports_streaming: bool = Field(
        True, description="Whether model supports streaming"
    )
    supports_tools: bool = Field(True, description="Whether model supports tool use")


MODELS_CONFIG_ENV = "CLAUDE_CODE_API_MODELS_PATH"
DEFAULT_MODELS_PATH = Path(__file__).resolve().parents[1] / "config" / "models.json"
MODEL_ID_PATTERN = re.compile(
    r"^claude-(?P<tier>[a-z]+)-(?P<major>\d+)-(?P<minor>\d+)(?:-(?P<stamp>\d+))?$"
)


def _models_config_path() -> Path:
    env_path = os.getenv(MODELS_CONFIG_ENV)
    if env_path:
        return Path(env_path).expanduser()
    return DEFAULT_MODELS_PATH


@lru_cache
def _load_models_config() -> Dict[str, Any]:
    path = _models_config_path()
    if not path.exists():
        raise FileNotFoundError(
            f"Models config not found at {path}. Set {MODELS_CONFIG_ENV} to override."
        )
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict) or "models" not in data:
        raise ValueError("Models config must contain a top-level 'models' list.")
    return data


def _model_index() -> Dict[str, ClaudeModelInfo]:
    config = _load_models_config()
    models = config.get("models", [])
    model_map: Dict[str, ClaudeModelInfo] = {}
    for entry in models:
        info = ClaudeModelInfo(**entry)
        model_map[info.id] = info
    return model_map


def _config_alias_pairs(raw_aliases: Any) -> List[tuple[str, str]]:
    if not isinstance(raw_aliases, dict):
        return []
    return [
        (alias, target)
        for alias, target in raw_aliases.items()
        if isinstance(alias, str) and isinstance(target, str)
    ]


def _entry_alias_pairs(entry: Any) -> List[tuple[str, str]]:
    if not isinstance(entry, dict):
        return []

    model_id = entry.get("id")
    model_aliases = entry.get("aliases", [])
    if not isinstance(model_id, str) or not isinstance(model_aliases, list):
        return []

    return [(alias, model_id) for alias in model_aliases if isinstance(alias, str)]


def _model_alias_index() -> Dict[str, str]:
    config = _load_models_config()
    aliases = dict(_config_alias_pairs(config.get("aliases", {})))
    for entry in config.get("models", []):
        aliases.update(_entry_alias_pairs(entry))
    return aliases


def _parse_model_id(model_id: str) -> Optional[tuple[str, int, int, int]]:
    match = MODEL_ID_PATTERN.match(model_id)
    if not match:
        return None

    stamp = match.group("stamp")
    return (
        match.group("tier"),
        int(match.group("major")),
        int(match.group("minor")),
        int(stamp) if stamp else 0,
    )


def _latest_model_for_tier(tier: str) -> Optional[str]:
    ranked_models = []
    for model_id in _model_index():
        parsed = _parse_model_id(model_id)
        if not parsed:
            continue
        parsed_tier, major, minor, stamp = parsed
        if parsed_tier != tier:
            continue
        ranked_models.append((major, minor, stamp, model_id))

    if not ranked_models:
        return None

    ranked_models.sort()
    return ranked_models[-1][3]


def _resolve_alias(model: str) -> Optional[str]:
    model_map = _model_index()
    target = _model_alias_index().get(model)
    if target and target in model_map:
        return target
    return None


# Utility functions for model validation
def validate_claude_model(model: str) -> str:
    """Validate and normalize Claude model name."""
    model_map = _model_index()
    normalized = (model or "").strip()

    if normalized in model_map:
        return normalized

    aliased = _resolve_alias(normalized)
    if aliased:
        return aliased

    parsed = _parse_model_id(normalized)
    if parsed and parsed[0] == "opus":
        latest_opus = _latest_model_for_tier("opus")
        if latest_opus:
            return latest_opus

    return get_default_model()


def get_default_model() -> str:
    """Get the default Claude model."""
    config = _load_models_config()
    default_model = config.get("default_model")
    if isinstance(default_model, str) and default_model:
        return default_model
    model_map = _model_index()
    if model_map:
        return next(iter(model_map.keys()))
    raise ValueError("Models config did not contain any models.")


def get_model_info(model_id: str) -> ClaudeModelInfo:
    """Get information about a Claude model."""
    model_map = _model_index()
    resolved_model_id = validate_claude_model(model_id)
    return model_map[resolved_model_id]


def get_available_models() -> List[ClaudeModelInfo]:
    """Get list of all available Claude models."""
    return list(_model_index().values())
