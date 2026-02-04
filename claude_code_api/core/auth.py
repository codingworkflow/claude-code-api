"""Authentication middleware and utilities."""

import time
from typing import Optional

import structlog
from fastapi import Request, status
from fastapi.responses import JSONResponse

from .config import settings

logger = structlog.get_logger()

# Simple in-memory rate limiting
rate_limit_store = {}


class RateLimiter:
    """Simple in-memory rate limiter."""

    def __init__(self, requests_per_minute: int = 60, burst: int = 10):
        self.requests_per_minute = requests_per_minute
        self.burst = burst
        self.store = {}

    def is_allowed(self, key: str) -> bool:
        """Check if request is allowed for the given key."""
        now = time.time()

        if key not in self.store:
            self.store[key] = {"requests": [], "burst_used": 0}

        user_data = self.store[key]

        # Remove old requests (older than 1 minute)
        user_data["requests"] = [
            req_time for req_time in user_data["requests"] if now - req_time < 60
        ]

        # Check burst limit
        if user_data["burst_used"] >= self.burst:
            # Reset burst if enough time has passed
            if len(user_data["requests"]) == 0:
                user_data["burst_used"] = 0
            else:
                return False

        # Check rate limit
        if len(user_data["requests"]) >= self.requests_per_minute:
            return False

        # Allow request
        user_data["requests"].append(now)
        user_data["burst_used"] += 1

        return True


# Global rate limiter instance
rate_limiter = RateLimiter(
    requests_per_minute=settings.rate_limit_requests_per_minute,
    burst=settings.rate_limit_burst,
)


def extract_api_key(request: Request) -> Optional[str]:
    """Extract API key from request headers."""
    # Check Authorization header (Bearer token)
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        return auth_header[7:]  # Remove "Bearer " prefix

    # Check x-api-key header
    api_key = request.headers.get("x-api-key")
    if api_key:
        return api_key

    # Check query parameter (less secure, but sometimes needed)
    api_key = request.query_params.get("api_key")
    if api_key:
        return api_key

    return None


def validate_api_key(api_key: str) -> bool:
    """Validate API key against configured keys."""
    if not settings.require_auth:
        return True

    if not settings.api_keys:
        logger.warning("No API keys configured but authentication is required")
        return False

    return api_key in settings.api_keys


async def auth_middleware(request: Request, call_next):
    """Authentication middleware."""
    # Skip auth for public endpoints
    public_paths = ["/", "/health", "/docs", "/redoc", "/openapi.json"]
    if request.url.path in public_paths:
        return await call_next(request)

    # Skip all auth and rate limiting when authentication is disabled (test mode)
    if not settings.require_auth:
        # Still set client_id for logging
        request.state.api_key = None
        request.state.client_id = "testclient"
        return await call_next(request)

    # Extract API key
    api_key = extract_api_key(request)

    # Validate API key if required
    if not api_key:
        logger.warning(
            "Missing API key",
            path=request.url.path,
            client_ip=request.client.host if request.client else "unknown",
        )
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={
                "error": {
                    "message": (
                        "Missing API key. Provide it via Authorization header "
                        "(Bearer token) or x-api-key header."
                    ),
                    "type": "authentication_error",
                    "code": "missing_api_key",
                }
            },
        )

    if not validate_api_key(api_key):
        logger.warning(
            "Invalid API key",
            path=request.url.path,
            client_ip=request.client.host if request.client else "unknown",
            api_key_prefix=api_key[:8] if api_key else "none",
        )
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={
                "error": {
                    "message": "Invalid API key",
                    "type": "authentication_error",
                    "code": "invalid_api_key",
                }
            },
        )

    # Rate limiting
    client_id = api_key or request.client.host if request.client else "anonymous"
    if not rate_limiter.is_allowed(client_id):
        logger.warning(
            "Rate limit exceeded", client_id=client_id, path=request.url.path
        )
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={
                "error": {
                    "message": "Rate limit exceeded",
                    "type": "rate_limit_error",
                    "code": "rate_limit_exceeded",
                }
            },
        )

    # Add API key to request state for downstream use
    request.state.api_key = api_key
    request.state.client_id = client_id

    return await call_next(request)
