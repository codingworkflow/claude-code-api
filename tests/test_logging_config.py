"""Tests for centralized logging configuration."""

import logging
from types import SimpleNamespace

import pytest
import structlog

from claude_code_api.core import logging_config


def test_minimal_event_filter_allows_warning_and_lifecycle_info():
    processor = logging_config._minimal_event_filter(False, "WARNING")
    assert processor is not None

    warning_event = {"event": "warning event"}
    assert processor(None, "warning", warning_event) is warning_event

    exception_event = {"event": "exception event"}
    assert processor(None, "exception", exception_event) is exception_event

    lifecycle_event = {"event": "Starting Claude Code API Gateway"}
    assert processor(None, "info", lifecycle_event) is lifecycle_event

    with pytest.raises(structlog.DropEvent):
        processor(None, "info", {"event": "suppressed info"})


def test_configure_logging_falls_back_to_console_when_file_handler_fails(monkeypatch):
    original_root = logging.getLogger()
    original_handlers = list(original_root.handlers)
    original_level = original_root.level

    def raise_oserror(*args, **kwargs):
        raise OSError("cannot create log file")

    monkeypatch.setattr(logging_config, "_create_file_handler", raise_oserror)

    settings = SimpleNamespace(
        debug=False,
        log_level="INFO",
        log_format="json",
        log_file_path="/not-writable/claude.log",
        log_to_file=True,
        log_max_bytes=1024,
        log_backup_count=1,
        log_to_console=False,
        log_min_level_when_not_debug="WARNING",
    )

    try:
        logging_config.configure_logging(settings)
        handlers = logging.getLogger().handlers
        assert handlers
        assert all(isinstance(handler, logging.StreamHandler) for handler in handlers)
    finally:
        root_logger = logging.getLogger()
        root_logger.handlers.clear()
        for handler in original_handlers:
            root_logger.addHandler(handler)
        root_logger.setLevel(original_level)
        structlog.reset_defaults()
