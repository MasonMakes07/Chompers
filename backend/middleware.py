"""Security middleware.

Rate limiting here protects the Google quota as much as the server: an
unthrottled endpoint is the one realistic way this app could cost money.
"""

import time
from collections import defaultdict, deque

from fastapi import Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from .config import get_settings

RATE_LIMIT_WINDOW_SECONDS = 60

# Headers applied to every response to harden the browser side.
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Permissions-Policy": "geolocation=(self), camera=(), microphone=()",
}


# ---------------------------------------------------------------------------


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Caps requests per client IP inside a rolling one-minute window."""

    # Prepares per-IP request timestamp queues.
    def __init__(self, app) -> None:
        super().__init__(app)
        self._settings = get_settings()
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    # Identifies the client, trusting the socket address over any header.
    @staticmethod
    def _client_key(request: Request) -> str:
        return request.client.host if request.client else "unknown"

    # Rejects the request if this IP has exceeded its per-minute allowance.
    async def dispatch(self, request: Request, call_next):
        if request.method == "OPTIONS":
            return await call_next(request)

        client_key = self._client_key(request)
        now = time.monotonic()
        recent_hits = self._hits[client_key]

        while recent_hits and now - recent_hits[0] > RATE_LIMIT_WINDOW_SECONDS:
            recent_hits.popleft()

        if len(recent_hits) >= self._settings.rate_limit_per_minute:
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={"detail": "Too many searches. Wait a minute and retry."},
            )

        recent_hits.append(now)
        return await call_next(request)


# ---------------------------------------------------------------------------


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """Rejects oversized bodies before they are parsed."""

    # Prepares the middleware with the configured byte ceiling.
    def __init__(self, app) -> None:
        super().__init__(app)
        self._max_bytes = get_settings().max_request_bytes

    # Blocks any request whose declared body exceeds the byte ceiling.
    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length and content_length.isdigit():
            if int(content_length) > self._max_bytes:
                return JSONResponse(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    content={"detail": "Request body too large."},
                )
        return await call_next(request)


# ---------------------------------------------------------------------------


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Attaches hardening headers to every outgoing response."""

    # Adds the standard security headers after the route runs.
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        for header_name, header_value in SECURITY_HEADERS.items():
            response.headers.setdefault(header_name, header_value)
        return response
