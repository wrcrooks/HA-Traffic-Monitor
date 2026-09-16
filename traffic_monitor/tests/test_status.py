"""M0 smoke test: the app imports and /api/status responds, entirely offline.

Run with: pip install -r ../app/requirements.txt httpx pytest && pytest
"""
from fastapi.testclient import TestClient

from app.main import app


def test_status_ok():
    client = TestClient(app)
    resp = client.get("/api/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "version" in body


def test_index_served():
    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"Traffic Monitor" in resp.content
