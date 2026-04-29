import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session as DBSession
from sqlalchemy.pool import StaticPool

from driftshield.api.app import create_app
from driftshield.db.models import Base, SessionModel


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


def test_create_behaviour_subject_and_event(client, auth_headers, db_session):
    session_id = uuid.uuid4()
    db_session.add(SessionModel(id=session_id, started_at=datetime.now(UTC), status="completed"))
    db_session.commit()

    subject_response = client.post(
        "/api/behaviour/subjects",
        headers=auth_headers,
        json={
            "subject_type": "trusted_pattern",
            "pattern_reference": "pattern:coverage-gap",
            "trust_band": "trusted",
            "surface": "api",
            "session_id": str(session_id),
        },
    )
    assert subject_response.status_code == 201
    subject = subject_response.json()
    assert subject["tracking_status"] == "live"
    assert subject["follow_up_status"] == "unavailable"

    event_response = client.post(
        "/api/behaviour/events",
        headers=auth_headers,
        json={
            "subject_id": subject["id"],
            "event_type": "pattern_viewed",
            "actor_id": "acct-1",
        },
    )
    assert event_response.status_code == 201
    event = event_response.json()
    assert event["event_type"] == "pattern_viewed"

    subject_after_view = client.get(
        f"/api/behaviour/subjects/{subject['id']}",
        headers=auth_headers,
    )
    assert subject_after_view.status_code == 200
    payload = subject_after_view.json()
    assert payload["event_counts"] == {"pattern_viewed": 1}
    assert payload["follow_up_status"] == "no_follow_up_observed"


def test_non_trusted_subjects_stay_unavailable_for_follow_up_metrics(client, auth_headers):
    response = client.post(
        "/api/behaviour/subjects",
        headers=auth_headers,
        json={
            "subject_type": "report",
            "pattern_reference": "report:session-1",
            "trust_band": "directional",
            "surface": "report",
        },
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["tracking_status"] == "unavailable"
    assert payload["follow_up_status"] == "unavailable"


def test_create_behaviour_subject_rejects_unknown_session_id(client, auth_headers):
    response = client.post(
        "/api/behaviour/subjects",
        headers=auth_headers,
        json={
            "subject_type": "trusted_pattern",
            "pattern_reference": "pattern:coverage-gap",
            "trust_band": "trusted",
            "surface": "api",
            "session_id": str(uuid.uuid4()),
        },
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Behaviour subject session not found"


def test_create_behaviour_event_rejects_unknown_linked_session_id(client, auth_headers):
    subject_response = client.post(
        "/api/behaviour/subjects",
        headers=auth_headers,
        json={
            "subject_type": "trusted_pattern",
            "pattern_reference": "pattern:coverage-gap",
            "trust_band": "trusted",
            "surface": "api",
        },
    )
    assert subject_response.status_code == 201
    subject_id = subject_response.json()["id"]

    response = client.post(
        "/api/behaviour/events",
        headers=auth_headers,
        json={
            "subject_id": subject_id,
            "event_type": "new_run_after_pattern_view",
            "linked_session_id": str(uuid.uuid4()),
        },
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Linked behaviour event session not found"


def test_ingest_creates_new_run_after_pattern_view_without_touching_telemetry(client, auth_headers, monkeypatch):
    viewed_at = "2026-04-29T16:30:00+00:00"
    subject_response = client.post(
        "/api/behaviour/subjects",
        headers=auth_headers,
        json={
            "subject_type": "trusted_pattern",
            "pattern_reference": "pattern:coverage-gap",
            "trust_band": "trusted",
            "surface": "ui",
            "first_exposed_at": viewed_at,
        },
    )
    assert subject_response.status_code == 201
    subject_id = subject_response.json()["id"]

    view_response = client.post(
        "/api/behaviour/events",
        headers=auth_headers,
        json={
            "subject_id": subject_id,
            "event_type": "pattern_viewed",
            "actor_id": "claude",
            "occurred_at": viewed_at,
        },
    )
    assert view_response.status_code == 201

    telemetry_calls: list[dict[str, object]] = []

    def fake_record_analysis_event(self, **kwargs):
        telemetry_calls.append(kwargs)
        return False

    monkeypatch.setattr(
        "driftshield.api.ingest_workflow.TelemetryService.record_analysis_event",
        fake_record_analysis_event,
    )

    transcript = "\n".join(
        [
            '{"sessionId":"behaviour-follow-up","type":"assistant","message":{"content":[{"type":"tool_use","id":"tool_1","name":"Read","input":{"file_path":"/tmp/test.txt"}}]},"timestamp":"2026-04-29T17:00:00+00:00"}',
            '{"sessionId":"behaviour-follow-up","type":"user","message":{"content":[{"type":"tool_result","tool_use_id":"tool_1","content":"ok"}]},"timestamp":"2026-04-29T17:00:01+00:00"}',
        ]
    ).encode()

    ingest_response = client.post(
        "/api/ingest",
        headers=auth_headers,
        files={"file": ("follow-up.jsonl", transcript, "application/jsonl")},
        data={"format": "claude_code"},
    )
    assert ingest_response.status_code == 201
    assert telemetry_calls

    subject_after_ingest = client.get(f"/api/behaviour/subjects/{subject_id}", headers=auth_headers)
    assert subject_after_ingest.status_code == 200
    payload = subject_after_ingest.json()
    assert payload["event_counts"]["pattern_viewed"] == 1
    assert payload["event_counts"]["new_run_after_pattern_view"] == 1
    assert payload["follow_up_status"] == "linked"
