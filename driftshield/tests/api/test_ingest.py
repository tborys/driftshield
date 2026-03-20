import io
import json
import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession
from sqlalchemy.pool import StaticPool

from driftshield.api.app import create_app
from driftshield.db.models import Base, DecisionNodeModel, SessionModel
from driftshield.db.persistence import IngestOutcome, PersistenceService


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
            "sessionId": "api-source-session-123",
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
            "sessionId": "api-source-session-123",
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


def _post_ingest(client, auth_headers, sample_transcript, filename="transcript.jsonl"):
    return client.post(
        "/api/ingest",
        headers=auth_headers,
        files={"file": (filename, io.BytesIO(sample_transcript), "application/jsonl")},
        data={"format": "claude_code"},
    )


def test_ingest_transcript(client, auth_headers, sample_transcript):
    response = _post_ingest(client, auth_headers, sample_transcript)
    assert response.status_code == 201
    data = response.json()
    assert "session_id" in data
    assert data["total_events"] >= 1
    assert data["status"] == "created"
    assert data["deduplicated"] is False


def test_ingest_persists_provenance_fields(client, auth_headers, sample_transcript, db_session):
    response = _post_ingest(
        client,
        auth_headers,
        sample_transcript,
        filename="uploads/daily/transcript.jsonl",
    )

    assert response.status_code == 201
    session = db_session.get(SessionModel, uuid.UUID(response.json()["session_id"]))
    assert session is not None
    assert session.transcript_hash is not None
    assert session.source_session_id == "api-source-session-123"
    assert session.source_path == "uploads/daily/transcript.jsonl"
    assert session.parser_version == "claude_code@1"
    assert session.ingested_at is not None


def test_reingest_is_explicit_dedupe_no_op(client, auth_headers, sample_transcript, db_session):
    first = _post_ingest(client, auth_headers, sample_transcript)
    second = _post_ingest(client, auth_headers, sample_transcript)

    assert first.status_code == 201
    assert second.status_code == 200

    first_data = first.json()
    second_data = second.json()

    assert first_data["status"] == "created"
    assert second_data["status"] == "deduped"
    assert second_data["deduplicated"] is True
    assert second_data["session_id"] == first_data["session_id"]
    assert second_data["total_events"] == first_data["total_events"]
    assert second_data["flagged_events"] == first_data["flagged_events"]
    assert second_data["has_inflection"] == first_data["has_inflection"]

    sessions = db_session.query(SessionModel).all()
    nodes = db_session.query(DecisionNodeModel).all()
    assert len(sessions) == 1
    assert len(nodes) == 1


def test_ingest_recovers_from_duplicate_commit_race(client, auth_headers, sample_transcript, monkeypatch):
    from driftshield.api.dependencies import get_db

    class FakeDB:
        def __init__(self):
            self.rolled_back = False

        def commit(self):
            raise IntegrityError("INSERT", {}, Exception("duplicate key"))

        def rollback(self):
            self.rolled_back = True

    fake_db = FakeDB()
    client.app.dependency_overrides[get_db] = lambda: fake_db

    session_id = uuid.uuid4()

    def fake_ingest(self, session, result, provenance):
        return IngestOutcome(
            session_id=session_id,
            total_events=1,
            flagged_events=0,
            has_inflection=False,
            status="created",
            deduplicated=False,
        )

    def fake_get_ingest_outcome(self, provenance):
        assert fake_db.rolled_back is True
        return IngestOutcome(
            session_id=session_id,
            total_events=1,
            flagged_events=0,
            has_inflection=False,
            status="deduped",
            deduplicated=True,
        )

    monkeypatch.setattr(PersistenceService, "ingest", fake_ingest)
    monkeypatch.setattr(PersistenceService, "get_ingest_outcome", fake_get_ingest_outcome)

    response = _post_ingest(client, auth_headers, sample_transcript)

    client.app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 200
    assert response.json() == {
        "session_id": str(session_id),
        "total_events": 1,
        "flagged_events": 0,
        "has_inflection": False,
        "status": "deduped",
        "deduplicated": True,
    }


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


def test_ingest_rejects_request_over_max_size_by_content_length(client, auth_headers, sample_transcript, monkeypatch):
    monkeypatch.setenv("MAX_REQUEST_BYTES", "32")
    oversized_client = TestClient(create_app())

    from driftshield.api.dependencies import get_db
    oversized_client.app.dependency_overrides[get_db] = lambda: client.app.dependency_overrides[get_db]()

    response = oversized_client.post(
        "/api/ingest",
        headers={**auth_headers, "content-length": "64"},
        files={"file": ("transcript.jsonl", io.BytesIO(sample_transcript), "application/jsonl")},
        data={"format": "claude_code"},
    )

    assert response.status_code == 413
    assert response.json()["detail"] == "Request body exceeds 32 bytes"



def test_ingest_rejects_invalid_content_length_header(client, auth_headers, sample_transcript, monkeypatch):
    monkeypatch.setenv("MAX_REQUEST_BYTES", "1024")
    oversized_client = TestClient(create_app())

    from driftshield.api.dependencies import get_db
    oversized_client.app.dependency_overrides[get_db] = lambda: client.app.dependency_overrides[get_db]()

    response = oversized_client.post(
        "/api/ingest",
        headers={**auth_headers, "content-length": "not-a-number"},
        files={"file": ("transcript.jsonl", io.BytesIO(sample_transcript), "application/jsonl")},
        data={"format": "claude_code"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid Content-Length header"
