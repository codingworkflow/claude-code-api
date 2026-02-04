"""Tests for time utilities and defaults."""

import os

from claude_code_api.core.config import default_project_root
from claude_code_api.utils.time import utc_now, utc_timestamp


def test_utc_time_helpers_monotonic():
    first = utc_now()
    second = utc_now()
    assert second >= first
    assert isinstance(utc_timestamp(), int)


def test_default_project_root_is_under_cwd():
    expected = os.path.join(os.getcwd(), "claude_projects")
    assert default_project_root() == expected
