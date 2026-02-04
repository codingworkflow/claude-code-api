"""Security utilities."""

import os
from pathlib import Path

import structlog
from fastapi import HTTPException, status

logger = structlog.get_logger()


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

        abs_base_path = Path(base_path).resolve()
        candidate_path = Path(path)
        if not candidate_path.is_absolute():
            candidate_path = abs_base_path / candidate_path

        resolved_path = candidate_path.resolve(strict=False)

        if not resolved_path.is_relative_to(abs_base_path):
            logger.warning(
                "Path traversal attempt detected",
                path=path,
                resolved_path=str(resolved_path),
                base_path=str(abs_base_path),
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid path: Path traversal detected",
            )

        return str(resolved_path)

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Path validation error", error=str(e), path=path)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid path: Path validation failed",
        )


def ensure_directory_within_base(
    path: str, base_path: str, *, allow_subpaths: bool = True
) -> str:
    """Validate a path within base_path and create the directory."""
    path_value = os.fspath(path)
    if not allow_subpaths:
        if os.path.isabs(path_value):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid path: Absolute paths are not allowed",
            )
        for sep in (os.path.sep, os.path.altsep):
            if sep and sep in path_value:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid path: Path separators are not allowed",
                )

    resolved_path = resolve_path_within_base(path_value, base_path)
    os.makedirs(resolved_path, exist_ok=True)
    return resolved_path


def validate_path(path: str, base_path: str) -> str:
    """Backward-compatible wrapper for path resolution."""
    return resolve_path_within_base(path, base_path)
