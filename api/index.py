"""Vercel serverless entry point.

Vercel's Python runtime serves the ASGI ``app`` exported here, and ``vercel.json``
routes every ``/api/*`` request to this module. The repo root is added to the path
so ``backend`` imports resolve when Vercel runs this file from ``api/``.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.main import app  # noqa: E402,F401
