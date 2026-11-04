"""Tests for the Vercel serverless entrypoint (api/index.py).

The entrypoint must expose the same FastAPI app as app.main so that the
deployed app behaves identically to the local one.
"""

import importlib.util
import os

from fastapi.testclient import TestClient

HERE = os.path.dirname(os.path.abspath(__file__))
ENTRYPOINT = os.path.join(HERE, "..", "api", "index.py")


def _load_entrypoint_app():
    spec = importlib.util.spec_from_file_location("vercel_entrypoint", ENTRYPOINT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.app


def test_entrypoint_exposes_the_same_app():
    app = _load_entrypoint_app()
    client = TestClient(app)

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}

    # The scripted demo is the serverless-safe flow: one POST returns the
    # transfers, their audit lines, and the stuck-transfer flag.
    response = client.post("/scenarios/run")
    assert response.status_code == 200
    by_name = {r["scenario"]: r for r in response.json()}
    assert by_name["clean"]["transfer"]["state"] == "completed"
    assert by_name["failed"]["transfer"]["state"] == "failed"
    assert by_name["manual_intervention"]["transfer"]["state"] == "manual_intervention"
    assert by_name["manual_intervention"]["next_action"] == "escalate, do not retry blindly"
    assert "audit_line" in by_name["manual_intervention"]


def test_entrypoint_strips_vercel_rewrite_prefix():
    # Live symptom (Nov 3): Vercel rewrote /health to the function path and
    # FastAPI answered {"detail": "Not Found"}. The entrypoint must route
    # the rewritten path to the same handler as the plain path.
    app = _load_entrypoint_app()
    client = TestClient(app)

    health = client.get("/api/index.py/health")
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}

    docs = client.get("/api/index.py/docs")
    assert docs.status_code == 200


def test_main_app_strips_prefix_and_serves_landing():
    # Nov 3 diagnostic proved Vercel serves app.main directly, bypassing
    # the entrypoint wrapper — so the strip must also live on the app
    # itself. The bare domain must serve a landing page, not a 404.
    import sys

    sys.path.insert(0, os.path.join(HERE, ".."))
    from app.main import app as main_app

    client = TestClient(main_app)

    health = client.get("/api/index.py/health")
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}

    landing = client.get("/")
    assert landing.status_code == 200
    assert "Reconciliation Harness" in landing.text
