"""Session HTTP routes."""

from fastapi.testclient import TestClient

from backend.main import app
from phases.phase_01.services.session import clear_all_sessions


def test_session_crud_flow():
    clear_all_sessions()
    client = TestClient(app)

    created = client.post("/api/session")
    assert created.status_code == 200
    body = created.json()
    session_id = body["session_id"]
    assert body["address_id"] is None

    fetched = client.get(f"/api/session/{session_id}")
    assert fetched.status_code == 200
    assert fetched.json()["session_id"] == session_id

    deleted = client.delete(f"/api/session/{session_id}")
    assert deleted.status_code == 200
    assert client.get(f"/api/session/{session_id}").status_code == 200  # recreates on get
