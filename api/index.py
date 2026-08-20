"""Vercel serverless entry point for the FastAPI backend.

`vercel.json` uses an explicit `builds` block, which disables Vercel's zero-config
framework auto-detection. That matters: the auto-detector scans the repo for a
FastAPI `app` variable, finds several (including one in the test suite), and fails
the build with "No FastAPI entrypoint found in default locations". Declaring the
build explicitly removes that guesswork, and the legacy `routes` entry hands this
function the original request path so `/api/health` reaches its route.

The repo root is added to `sys.path` so `backend` imports resolve when Vercel runs
this file from `api/`.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.main import app  # noqa: E402


# ---------------------------------------------------------------------------


class EnsureApiPrefix:
    """Restores the `/api` prefix if the platform strips it before dispatch."""

    # Stores the ASGI app this middleware wraps.
    def __init__(self, asgi_app) -> None:
        self._asgi_app = asgi_app

    # Prefixes the request path with /api when it is missing, then delegates.
    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            path = scope.get("path", "")
            if not path.startswith("/api"):
                scope = dict(scope)
                scope["path"] = "/api" + path
        await self._asgi_app(scope, receive, send)


# Vercel's catch-all should deliver the full path, but normalize defensively so a
# stripped prefix cannot 404 every route. Local runs never see this.
if os.getenv("VERCEL"):
    app.add_middleware(EnsureApiPrefix)
