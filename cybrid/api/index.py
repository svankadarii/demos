"""Vercel serverless entrypoint for the Cybrid reconciliation harness.

Vercel's Python runtime serves the ASGI app defined here. The FastAPI app
itself lives in app/main.py and is unchanged; this file only re-exports it
so Vercel can find it.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.main import app  # noqa: E402,F401  (re-exported for Vercel)
