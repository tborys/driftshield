import io
import json
import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session as DBSession
from sqlalchemy.pool import StaticPool

from driftshield.api.app import create_app
from driftshield.db.models import Base


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with DBSession(engine) as session:
        yield session


@pytest.fixture
def client(db_session, monkeypatch):
    monkeypatch.setenv("API_KEY", "test-key")
    app = create_app()

    from driftshield.api.dependencies import get_db
    app.dependency_overrides[get_db] = lambda: db_session

    return TestClient(app)


@pytest.fixture
def auth_headers():
    return {"X-API-Key": "test-key"}


@pytest.fixture
def sample_transcript():
    """Minimal Claude Code-style JSONL transcript."""
    lines = [
        {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tool_1",
                        "name": "Read",
                        "input": {"file_path": "/test.py"},
                    }
                ]
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
        {
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "tool_1",
                        "content": "file contents here",
                    }
                ]
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    ]
    content = "\n".join(json.dumps(line) for line in lines)
    return content.encode()


def test_ingest_transcript(client, auth_headers, sample_transcript):
    response = client.post(
        "/api/ingest",
        headers=auth_headers,
        files={"file": ("transcript.jsonl", io.BytesIO(sample_transcript), "application/jsonl")},
        data={"format": "claude_code"},
    )
    assert response.status_code == 201
    data = response.json()
    assert "session_id" in data
    assert data["total_events"] >= 1


def test_ingest_without_auth(client, sample_transcript):
    response = client.post(
        "/api/ingest",
        files={"file": ("transcript.jsonl", io.BytesIO(sample_transcript), "application/jsonl")},
    )
    assert response.status_code == 401


def test_ingest_unsupported_format(client, auth_headers):
    response = client.post(
        "/api/ingest",
        headers=auth_headers,
        files={"file": ("test.txt", io.BytesIO(b"not a transcript"), "text/plain")},
        data={"format": "unknown-format"},
    )
    assert response.status_code == 422
