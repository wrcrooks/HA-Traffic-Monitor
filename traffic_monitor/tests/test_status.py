"""Smoke tests: the app imports, its lifespan starts/stops cleanly with
nothing configured (the out-of-the-box state before a user sets an API
key/route), and /api/status responds. Entirely offline.

Run with: pip install -r ../requirements-dev.txt && pytest
"""
from fastapi.testclient import TestClient

from app.main import app


def test_status_ok():
    # `with` triggers the lifespan (startup/shutdown) -- without it,
    # app.state is never populated at all. With no TM_API_KEY/TM_MQTT_HOST/
    # route configured in the test environment, lifespan takes its "not
    # configured yet" branch and starts no background tasks, which is
    # exactly the state a fresh install is in.
    with TestClient(app) as client:
        resp = client.get("/api/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "version" in body
    assert body["api_requests_remaining"] is None  # no budget guard started


def test_index_served():
    with TestClient(app) as client:
        resp = client.get("/")
    assert resp.status_code == 200
    assert b"Traffic Monitor" in resp.content
