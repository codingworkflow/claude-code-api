"""Security utilities."""

import os
import structlog
from fastapi import HTTPException, status
from typing import Optional

logger = structlog.get_logger()

def validate_path(path: str, base_path: str) -> str:
    """
    Validate that a path is safe and within the base path.
    Prevents directory traversal attacks.

    Args:
        path: The path to validate (can be absolute or relative)
        base_path: The allowed base directory

    Returns:
        The normalized absolute path if valid

    Raises:
        HTTPException: If path is invalid or outside base_path
    """
    try:
        # Normalize base path to absolute path
        abs_base_path = os.path.abspath(base_path)

        # Handle relative paths by joining with base_path
        if not os.path.isabs(path):
            abs_path = os.path.abspath(os.path.join(abs_base_path, path))
        else:
            abs_path = os.path.abspath(path)

        # Check if path is within base_path
        # os.path.commonpath returns the longest common sub-path
        # If valid, commonpath should be equal to base_path
        if os.path.commonpath([abs_base_path, abs_path]) != abs_base_path:
            logger.warning(
                "Path traversal attempt detected",
                path=path,
                resolved_path=abs_path,
                base_path=abs_base_path
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid path: Path traversal detected"
            )

        return abs_path

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Path validation error", error=str(e), path=path)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid path: {str(e)}"
        )
