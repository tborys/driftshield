import pytest
from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient

from driftshield.api.auth import require_api_key


@pytest.fixture
def protected_app():
    app = FastAPI()

    @app.get("/protected")
    def protected_route(api_key: str = Depends(require_api_key)):
        return {"message": "ok"}

    return app


def test_request_without_api_key_returns_401(protected_app, monkeypatch):
    monkeypatch.setenv("API_KEY", "test-key-123")
    client = TestClient(protected_app)
    response = client.get("/protected")
    assert response.status_code == 401
    assert response.json()["detail"] == "Missing or invalid API key"


def test_request_with_wrong_api_key_returns_401(protected_app, monkeypatch):
    monkeypatch.setenv("API_KEY", "test-key-123")
    client = TestClient(protected_app)
    response = client.get("/protected", headers={"X-API-Key": "wrong-key"})
    assert response.status_code == 401


def test_request_with_valid_api_key_returns_200(protected_app, monkeypatch):
    monkeypatch.setenv("API_KEY", "test-key-123")
    client = TestClient(protected_app)
    response = client.get("/protected", headers={"X-API-Key": "test-key-123"})
    assert response.status_code == 200
    assert response.json()["message"] == "ok"
