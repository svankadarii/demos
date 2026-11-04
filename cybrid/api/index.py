"""Vercel serverless entrypoint for the Cybrid reconciliation harness.

Vercel's Python runtime serves the ASGI app defined here. The FastAPI app
itself lives in app/main.py and is unchanged; this file only re-exports it
so Vercel can find it, wrapped in a small prefix stripper (see below).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.main import app as _fastapi_app  # noqa: E402


class _StripEntrypointPrefix:
    """Pure-ASGI wrapper: strip a Vercel rewrite prefix before routing.

    Live symptom (Nov 3): Vercel rewrote /health to the function path and
    FastAPI answered {"detail": "Not Found"}. When the request arrives
    carrying the rewritten path (/api/index.py/health), route the original
    path (/health) instead. No-op for normal paths.

    A wrapper (rather than add_middleware on the shared app) keeps this
    idempotent: re-importing this module always wraps the original
    app.main app, never a wrapped one, and never touches middleware state
    after the app has started.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            path = scope["path"]
            for prefix in ("/api/index.py", "/api/index"):
                if path == prefix:
                    scope["path"] = "/"
                    break
                if path.startswith(prefix + "/"):
                    scope["path"] = path[len(prefix):]
                    break
        await self.app(scope, receive, send)


app = _StripEntrypointPrefix(_fastapi_app)
