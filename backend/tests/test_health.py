from fastapi.testclient import TestClient

from civicflow.config import Settings
from civicflow.main import create_app


def test_health():
    with TestClient(create_app(Settings(_env_file=None))) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_docs_and_openapi():
    with TestClient(create_app(Settings(_env_file=None))) as client:
        assert client.get("/docs").status_code == 200
        response = client.get("/openapi.json")

    assert response.status_code == 200
    assert "/health" in response.json()["paths"]
