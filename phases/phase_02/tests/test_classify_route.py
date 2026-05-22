"""HTTP POST /api/classify."""

from fastapi.testclient import TestClient

from backend.main import app
from phases.phase_01.services.session import clear_all_sessions


def test_classify_endpoint():
    clear_all_sessions()
    client = TestClient(app)

    session = client.post("/api/session").json()
    sid = session["session_id"]

    resp = client.post(
        "/api/classify",
        json={"session_id": sid, "message": "hi there"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["route"] == "greeting"
    assert body["bubbles"]
