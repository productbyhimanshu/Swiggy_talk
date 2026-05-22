"""FastAPI health endpoint smoke test."""

from fastapi.testclient import TestClient

from backend.main import app


def test_health_endpoint():
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["order_enabled"] is False
    assert data["orders_allowed"] is False
