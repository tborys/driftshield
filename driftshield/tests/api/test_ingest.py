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
from driftshield.telemetry import TelemetryService


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
    from driftshield.core.analysis.session import AnalysisResult
    from driftshield.core.graph.models import LineageGraph

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

    def fake_ingest_bytes(self, *, raw_bytes, parser_name, source_path, existing_session_id=None):
        analysis_result = AnalysisResult(
            events=[],
            graph=LineageGraph(session_id=str(session_id)),
            inflection_node=None,
            total_events=1,
            flagged_events=0,
            inflection_explanation=None,
        )
        return (
            IngestOutcome(
                session_id=session_id,
                total_events=1,
                flagged_events=0,
                has_inflection=False,
                status="created",
                deduplicated=False,
            ),
            analysis_result,
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

    emit_calls = []

    def fake_record_analysis_event(self, **kwargs):
        emit_calls.append(kwargs)
        return True

    monkeypatch.setattr("driftshield.api.routes.ingest.TranscriptIngestService.ingest_bytes", fake_ingest_bytes)
    monkeypatch.setattr(PersistenceService, "get_ingest_outcome", fake_get_ingest_outcome)
    monkeypatch.setattr("driftshield.api.routes.ingest.TelemetryService.record_analysis_event", fake_record_analysis_event)

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
    assert emit_calls == []


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


def test_ingest_emits_unclassified_phase_2a_metrics_when_telemetry_is_enabled(client, auth_headers, sample_transcript, monkeypatch, tmp_path):
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))
    TelemetryService().enable()

    response = _post_ingest(client, auth_headers, sample_transcript)

    assert response.status_code == 201
    events = TelemetryService().read_events()
    analysis_event = events[-1]
    assert analysis_event["event_type"] == "analysis_result"
    assert analysis_event["payload"] == {
        "classifiable": True,
        "event_inventory_version": "phase-2a-v1",
        "match_count": 0,
        "mixed_family": False,
        "not_classifiable_reason": None,
        "outcome_status": "unclassified",
        "primary_family_id": None,
    }


def test_ingest_emits_matched_phase_2a_metrics_when_analysis_flags_risk(client, auth_headers, sample_transcript, monkeypatch, tmp_path):
    from driftshield.core.analysis.session import AnalysisResult
    from driftshield.core.graph.models import LineageGraph
    from driftshield.core.models import ExplanationPayload, RiskClassification

    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))
    TelemetryService().enable()

    original_events = []

    def fake_analyze_session(events, session_id=None):
        original_events.extend(events)
        events[0].risk_classification = RiskClassification(
            coverage_gap=True,
            explanations={"coverage_gap": ExplanationPayload(reason="missing context")},
        )
        return AnalysisResult(
            events=events,
            graph=LineageGraph(session_id=session_id or events[0].session_id),
            inflection_node=None,
            total_events=len(events),
            flagged_events=1,
            inflection_explanation=None,
        )

    monkeypatch.setattr("driftshield.db.ingest_service.analyze_session", fake_analyze_session)

    response = _post_ingest(client, auth_headers, sample_transcript)

    assert response.status_code == 201
    analysis_event = TelemetryService().read_events()[-1]
    assert analysis_event["event_type"] == "analysis_result"
    assert analysis_event["payload"] == {
        "classifiable": True,
        "event_inventory_version": "phase-2a-v1",
        "match_count": 1,
        "mixed_family": False,
        "not_classifiable_reason": None,
        "outcome_status": "matched",
        "primary_family_id": "coverage_gap",
    }


def test_deduped_ingest_does_not_emit_duplicate_metrics(client, auth_headers, sample_transcript, monkeypatch, tmp_path):
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))
    TelemetryService().enable()

    first = _post_ingest(client, auth_headers, sample_transcript)
    second = _post_ingest(client, auth_headers, sample_transcript)

    assert first.status_code == 201
    assert second.status_code == 200
    analysis_events = [
        event for event in TelemetryService().read_events() if event["event_type"] == "analysis_result"
    ]
    assert len(analysis_events) == 1


def test_ingest_succeeds_even_when_post_commit_telemetry_emit_fails(client, auth_headers, sample_transcript, monkeypatch):
    def fail_record_analysis_event(self, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(
        "driftshield.api.routes.ingest.TelemetryService.record_analysis_event",
        fail_record_analysis_event,
    )

    response = _post_ingest(client, auth_headers, sample_transcript)

    assert response.status_code == 201
    assert response.json()["status"] == "created"
