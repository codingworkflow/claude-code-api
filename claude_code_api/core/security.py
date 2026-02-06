"""Security utilities."""

import os
import re

import structlog
from fastapi import HTTPException, status

logger = structlog.get_logger()

PATH_TRAVERSAL_MSG = "Invalid path: Path traversal detected"


def _bad_request(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def _ensure_leaf_path(path_value: str) -> None:
    if os.path.isabs(path_value):
        raise _bad_request("Invalid path: Absolute paths are not allowed")
    for sep in (os.path.sep, os.path.altsep):
        if sep and sep in path_value:
            raise _bad_request("Invalid path: Path separators are not allowed")


def _sanitize_leaf_value(path_value: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9._-]", "_", path_value)
    if not sanitized.strip("._-"):
        raise _bad_request("Invalid path: Path is required")
    return sanitized


def _ensure_within_base(path_value: str, base_path: str, resolved_path: str) -> None:
    abs_base_path = os.path.realpath(base_path)
    abs_resolved_path = os.path.realpath(resolved_path)
    try:
        common_path = os.path.commonpath([abs_base_path, abs_resolved_path])
    except ValueError:
        common_path = ""
    if common_path != abs_base_path:
        logger.warning(
            "Path traversal attempt detected (post-validate)",
            path=path_value,
            resolved_path=resolved_path,
            base_path=abs_base_path,
        )
        raise _bad_request(PATH_TRAVERSAL_MSG)


def resolve_path_within_base(path: str, base_path: str) -> str:
    """
    Resolve a user-provided path within a base directory.
    Prevents directory traversal and symlink escapes.

    Args:
        path: The path to resolve (can be absolute or relative)
        base_path: The allowed base directory

    Returns:
        The normalized absolute path if valid

    Raises:
        HTTPException: If path is invalid or outside base_path
    """
    try:
        if path is None or not str(path).strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid path: Path is required",
            )
        if "\x00" in str(path):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid path: Null byte detected",
            )

        abs_base_path = os.path.realpath(base_path)
        path_value = os.fspath(path)
        normalized_path = os.path.normpath(path_value)
        if not os.path.isabs(normalized_path):
            if normalized_path == ".." or normalized_path.startswith(f"..{os.path.sep}"):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=PATH_TRAVERSAL_MSG,
                )
        if os.path.isabs(normalized_path):
            resolved_path = os.path.realpath(normalized_path)
        else:
            resolved_path = os.path.realpath(os.path.join(abs_base_path, normalized_path))

        try:
            common_path = os.path.commonpath([abs_base_path, resolved_path])
        except ValueError:
            common_path = ""

        if common_path != abs_base_path:
            logger.warning(
                "Path traversal attempt detected",
                path=path,
                resolved_path=resolved_path,
                base_path=abs_base_path,
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=PATH_TRAVERSAL_MSG,
            )

        return resolved_path

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Path validation error", error=str(e), path=path)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid path: Path validation failed",
        )


def ensure_directory_within_base(
    path: str,
    base_path: str,
    *,
    allow_subpaths: bool = True,
    sanitize_leaf: bool = False,
) -> str:
    """Validate a path within base_path and create the directory."""
    path_value = os.fspath(path)
    if not allow_subpaths:
        _ensure_leaf_path(path_value)

    if sanitize_leaf:
        if allow_subpaths:
            raise _bad_request("Invalid path: Sanitization only allowed for leaf paths")
        path_value = _sanitize_leaf_value(path_value)

    resolved_path = resolve_path_within_base(path_value, base_path)
    _ensure_within_base(path_value, base_path, resolved_path)
    try:
        os.makedirs(resolved_path, exist_ok=True)  # codeql[py/path-injection]
    except FileExistsError as e:
        raise _bad_request(
            f"Invalid path: {resolved_path} exists and is not a directory"
        ) from e
    return resolved_path


def validate_path(path: str, base_path: str) -> str:
    """Backward-compatible wrapper for path resolution."""
    return resolve_path_within_base(path, base_path)
