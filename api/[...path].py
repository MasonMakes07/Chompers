"""Vercel serverless entry point for the FastAPI backend.

Named as a catch-all (`[...path].py`) so Vercel's filesystem routing sends every
`/api/*` request here **with the original path intact**. A plain `index.py` plus a
`vercel.json` rewrite does not work: the rewrite destination is a fixed string, so
FastAPI would receive `/api/index` and 404 on every real route.

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
