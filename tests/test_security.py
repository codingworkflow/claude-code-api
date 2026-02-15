import os

import pytest
from fastapi import HTTPException

from claude_code_api.core.security import validate_path


def test_validate_path_valid():
    base = "/tmp/projects"
    path = "project1"
    expected = os.path.realpath(os.path.join(base, "project1"))
    assert validate_path(path, base) == expected


def test_validate_path_traversal():
    base = "/tmp/projects"
    path = "../etc/passwd"
    with pytest.raises(HTTPException) as exc:
        validate_path(path, base)
    assert exc.value.status_code == 400
    assert "Path traversal detected" in exc.value.detail


def test_validate_path_absolute_traversal():
    base = "/tmp/projects"
    path = "/etc/passwd"
    with pytest.raises(HTTPException) as exc:
        validate_path(path, base)
    assert exc.value.status_code == 400
    assert "Path traversal detected" in exc.value.detail


def test_validate_path_absolute_valid():
    base = "/tmp/projects"
    path = "/tmp/projects/project1"
    expected = os.path.realpath(path)
    assert validate_path(path, base) == expected
