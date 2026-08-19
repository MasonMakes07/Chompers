"""Security middleware.

Rate limiting protects the upstream provider more than this server. Every
search costs a Google Places call, so an unthrottled endpoint is the one
realistic way this app could cost money or exhaust a quota.

Three independent limits, because each stops a different attack:

1. Burst   - a short window, so a client cannot fire its whole minute's
             allowance in one second.
2. Sustained - a rolling minute, so a client cannot drip steadily forever.
3. Global  - across every client, so many IPs cannot together drain the
             upstream quota that a per-IP limit alone would happily allow.
"""

import time
from collections import OrderedDict, deque

from fastapi import Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from .config import get_settings

RATE_LIMIT_WINDOW_SECONDS = 60

# A short window is what actually stops a burst. Without it, a minute's worth
# of requests can all land in the same second and every one is allowed.
BURST_WINDOW_SECONDS = 10

# Cheap local endpoints that never touch an upstream service and so are not
# worth spending a client's search budget on.
RATE_LIMIT_EXEMPT_PATHS = frozenset({"/api/health", "/docs", "/openapi.json"})

# Request timestamps per client IP, most recently seen last. Module level so
# the counters survive app reloads and can be cleared between tests.
_HITS: "OrderedDict[str, deque[float]]" = OrderedDict()

# Timestamps across every client, protecting the shared upstream quota.
_GLOBAL_HITS: "deque[float]" = deque()


# Clears all rate-limit state. Used by tests; never called in production.
def reset_rate_limits() -> None:
    _HITS.clear()
    _GLOBAL_HITS.clear()


# Drops timestamps that have aged out of the given window.
def _prune(hits: "deque[float]", now: float, window_seconds: float) -> None:
    while hits and now - hits[0] > window_seconds:
        hits.popleft()


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
    """Caps burst, sustained, and total request rates before any upstream call."""

    # Prepares the middleware with the configured allowances.
    def __init__(self, app) -> None:
        super().__init__(app)
        self._settings = get_settings()

    # Identifies the client, honoring X-Forwarded-For only when configured.
    #
    # That header is attacker-controlled, so it is ignored entirely unless
    # trusted_proxy_count states how many proxies sit in front. The client
    # IP is then read that many hops from the right of the chain, the only
    # position a forged left-hand entry cannot occupy. A chain shorter than
    # expected is treated as spoofed and falls back to the socket peer.
    def _client_key(self, request: Request) -> str:
        proxy_count = self._settings.trusted_proxy_count
        if proxy_count > 0:
            forwarded = request.headers.get("x-forwarded-for", "")
            chain = [addr.strip() for addr in forwarded.split(",") if addr.strip()]
            if len(chain) >= proxy_count:
                return chain[-proxy_count]
        return request.client.host if request.client else "unknown"

    # Returns this client's timestamp log, bounding how many clients we track.
    def _hits_for(self, client_key: str) -> "deque[float]":
        hits = _HITS.get(client_key)
        if hits is None:
            hits = deque()
            _HITS[client_key] = hits
            # An unbounded table is a memory exhaustion vector, since an
            # attacker can cycle source addresses cheaply over IPv6.
            while len(_HITS) > self._settings.max_tracked_clients:
                _HITS.popitem(last=False)
        else:
            _HITS.move_to_end(client_key)
        return hits

    # Builds the 429 response, telling the client how long to wait.
    @staticmethod
    def _too_many(detail: str, retry_after_seconds: int) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={"detail": detail},
            headers={"Retry-After": str(retry_after_seconds)},
        )

    # Rejects the request if any of the three limits is already exhausted.
    async def dispatch(self, request: Request, call_next):
        if request.method == "OPTIONS":
            return await call_next(request)
        if request.url.path in RATE_LIMIT_EXEMPT_PATHS:
            return await call_next(request)

        now = time.monotonic()
        client_key = self._client_key(request)
        hits = self._hits_for(client_key)

        _prune(hits, now, RATE_LIMIT_WINDOW_SECONDS)
        _prune(_GLOBAL_HITS, now, RATE_LIMIT_WINDOW_SECONDS)

        # Burst: how many of this client's recent hits are very recent.
        burst_count = sum(
            1 for stamp in hits if now - stamp <= BURST_WINDOW_SECONDS
        )
        if burst_count >= self._settings.rate_limit_burst:
            return self._too_many(
                "Too many searches at once. Wait a few seconds and retry.",
                BURST_WINDOW_SECONDS,
            )

        if len(hits) >= self._settings.rate_limit_per_minute:
            return self._too_many(
                "Too many searches. Wait a minute and retry.",
                RATE_LIMIT_WINDOW_SECONDS,
            )

        if len(_GLOBAL_HITS) >= self._settings.global_rate_limit_per_minute:
            return self._too_many(
                "The service is busy right now. Try again shortly.",
                RATE_LIMIT_WINDOW_SECONDS,
            )

        hits.append(now)
        _GLOBAL_HITS.append(now)
        return await call_next(request)


# ---------------------------------------------------------------------------


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """Rejects oversized bodies before they are parsed."""

    # Prepares the middleware with the configured byte ceiling.
    def __init__(self, app) -> None:
        super().__init__(app)
        self._max_bytes = get_settings().max_request_bytes

    # Builds the 413 response for a body that is too large or unmeasurable.
    @staticmethod
    def _too_large() -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            content={"detail": "Request body too large."},
        )

    # Blocks any request whose body exceeds, or could hide exceeding, the cap.
    async def dispatch(self, request: Request, call_next):
        # A chunked body carries no Content-Length for the check below to
        # read, so it could stream past the cap unmeasured. This JSON API's
        # clients always send a length, so a chunked upload is refused rather
        # than trusted through unchecked.
        transfer_encoding = request.headers.get("transfer-encoding", "")
        if "chunked" in transfer_encoding.lower():
            return self._too_large()

        content_length = request.headers.get("content-length")
        if content_length is not None:
            # A non-numeric or oversized length is rejected outright; trusting
            # a malformed value is exactly the gap being closed here.
            if not content_length.isdigit() or int(content_length) > self._max_bytes:
                return self._too_large()
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
