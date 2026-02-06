"""Centralized logging configuration."""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from typing import Any

import structlog

_LIFECYCLE_EVENTS = {
    "Starting Claude Code API Gateway",
    "Database initialized",
    "Managers initialized",
    "Claude Code available",
    "Shutting down Claude Code API Gateway",
    "Shutdown complete",
}
_DEFAULT_LOG_LEVEL = logging.INFO
_DEFAULT_MIN_NON_DEBUG_LEVEL = logging.WARNING
_DEFAULT_MAX_BYTES = 10 * 1024 * 1024
_DEFAULT_BACKUP_COUNT = 5
_METHOD_LEVELS = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "warn": logging.WARNING,
    "error": logging.ERROR,
    "critical": logging.CRITICAL,
    "exception": logging.ERROR,
}


def _coerce_log_level(level_name: str | None, debug_enabled: bool) -> int:
    if debug_enabled:
        return logging.DEBUG
    if not level_name:
        return _DEFAULT_LOG_LEVEL
    return getattr(logging, str(level_name).upper(), _DEFAULT_LOG_LEVEL)


def _ensure_parent_dir(file_path: str) -> None:
    parent_dir = os.path.dirname(file_path)
    if parent_dir:
        os.makedirs(parent_dir, exist_ok=True)


def _create_file_handler(
    file_path: str, max_bytes: int, backup_count: int
) -> logging.Handler:
    _ensure_parent_dir(file_path)
    handler = RotatingFileHandler(
        filename=file_path,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    if os.path.exists(file_path) and os.path.getsize(file_path) > max_bytes:
        handler.doRollover()
    return handler


def _minimal_event_filter(debug_enabled: bool, min_level_name: str | None):
    if debug_enabled:
        return None

    min_level = getattr(
        logging, str(min_level_name or "").upper(), _DEFAULT_MIN_NON_DEBUG_LEVEL
    )

    def _processor(
        logger: Any, method_name: str, event_dict: dict[str, Any]
    ) -> dict[str, Any]:
        level = _METHOD_LEVELS.get(method_name.lower(), logging.INFO)
        if level >= min_level:
            return event_dict
        if event_dict.get("lifecycle") is True:
            return event_dict
        if event_dict.get("event") in _LIFECYCLE_EVENTS:
            return event_dict
        raise structlog.DropEvent

    return _processor


def _build_processors(
    debug_enabled: bool, log_format: str, min_level_name: str | None
) -> list[Any]:
    processors: list[Any] = [structlog.stdlib.filter_by_level]
    minimal_filter = _minimal_event_filter(debug_enabled, min_level_name)
    if minimal_filter:
        processors.append(minimal_filter)

    processors.extend(
        [
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
        ]
    )

    if str(log_format).lower() == "json":
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())

    return processors


def configure_logging(settings: Any) -> None:
    """Configure structured logging once for the whole application."""
    debug_enabled = bool(getattr(settings, "debug", False))
    log_level = _coerce_log_level(getattr(settings, "log_level", None), debug_enabled)
    log_format = getattr(settings, "log_format", "json")
    log_file_path = getattr(settings, "log_file_path", "dist/logs/claude-code-api.log")
    log_to_file = bool(getattr(settings, "log_to_file", True))
    log_max_bytes = int(getattr(settings, "log_max_bytes", _DEFAULT_MAX_BYTES))
    log_backup_count = int(getattr(settings, "log_backup_count", _DEFAULT_BACKUP_COUNT))
    log_to_console = bool(getattr(settings, "log_to_console", True))
    log_min_level = getattr(settings, "log_min_level_when_not_debug", "WARNING")

    handlers: list[logging.Handler] = []
    if log_to_file and log_file_path:
        try:
            handlers.append(
                _create_file_handler(log_file_path, log_max_bytes, log_backup_count)
            )
        except OSError as exc:
            print(
                f"Failed to initialize log file handler for {log_file_path}: {exc}. "
                "Continuing with console logging only.",
                file=sys.stderr,
            )

    if log_to_console or not handlers:
        handlers.append(logging.StreamHandler())

    formatter = logging.Formatter("%(message)s")
    for handler in handlers:
        handler.setLevel(log_level)
        handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.handlers.clear()
    for handler in handlers:
        root_logger.addHandler(handler)

    if not debug_enabled:
        logging.getLogger("uvicorn.access").setLevel(logging.ERROR)
        logging.getLogger("uvicorn.error").setLevel(logging.ERROR)

    structlog.configure(
        processors=_build_processors(debug_enabled, log_format, log_min_level),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
