"""Time helpers for consistent UTC timestamps."""

from datetime import datetime, timezone


def utc_now() -> datetime:
    """Return a naive UTC datetime (timezone stripped for storage compatibility)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def utc_timestamp() -> int:
    """Return a UTC unix timestamp in seconds."""
    return int(datetime.now(timezone.utc).timestamp())
