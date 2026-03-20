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


def test_request_without_configured_api_key_returns_503(protected_app, monkeypatch):
    monkeypatch.delenv("API_KEY", raising=False)
    client = TestClient(protected_app)
    response = client.get("/protected", headers={"X-API-Key": "anything"})
    assert response.status_code == 503
    assert response.json()["detail"] == "API key is not configured"


@pytest.mark.parametrize("placeholder_key", ["your-api-key-here", "replace-with-a-long-random-api-key"])
def test_request_with_placeholder_api_key_in_production_returns_503(protected_app, monkeypatch, placeholder_key):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("API_KEY", placeholder_key)
    client = TestClient(protected_app)
    response = client.get("/protected", headers={"X-API-Key": placeholder_key})
    assert response.status_code == 503
    assert response.json()["detail"] == "API key is not safely configured for production"
