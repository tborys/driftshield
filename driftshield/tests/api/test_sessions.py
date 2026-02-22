import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session as DBSession
from sqlalchemy.pool import StaticPool

from driftshield.api.app import create_app
from driftshield.db.models import (
    Base,
    DecisionNodeModel,
    RecurrenceSignatureModel,
    SessionModel,
    SessionSignatureModel,
)


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
def seeded_session(db_session):
    session_id = uuid.uuid4()
    s = SessionModel(
        id=session_id,
        agent_id="test-agent",
        started_at=datetime.now(timezone.utc),
        status="completed",
    )
    node = DecisionNodeModel(
        id=uuid.uuid4(),
        session_id=session_id,
        sequence_num=1,
        event_type="TOOL_CALL",
        action="read_file",
        coverage_gap=True,
        is_inflection_node=True,
    )
    db_session.add_all([s, node])
    db_session.commit()
    return session_id


def test_list_sessions(client, auth_headers, seeded_session):
    response = client.get("/api/sessions", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert len(data["items"]) == 1
    assert data["items"][0]["agent_id"] == "test-agent"


def test_list_sessions_pagination(client, auth_headers, db_session):
    now = datetime.now(timezone.utc)
    for i in range(5):
        db_session.add(SessionModel(
            id=uuid.uuid4(), agent_id=f"agent-{i}", started_at=now, status="completed"
        ))
    db_session.commit()

    response = client.get("/api/sessions?page=1&per_page=2", headers=auth_headers)
    data = response.json()
    assert data["total"] == 5
    assert len(data["items"]) == 2
    assert data["pages"] == 3


def test_get_session_detail(client, auth_headers, seeded_session):
    response = client.get(f"/api/sessions/{seeded_session}", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(seeded_session)
    assert data["agent_id"] == "test-agent"


def test_session_endpoints_include_recurrence_summary(client, auth_headers, db_session):
    session_id = uuid.uuid4()
    s = SessionModel(
        id=session_id,
        agent_id="test-agent",
        started_at=datetime.now(timezone.utc),
        status="completed",
    )
    sig_id = uuid.uuid4()
    sig = RecurrenceSignatureModel(
        id=sig_id,
        signature_hash="abc123",
        pattern={"level": "recurring", "probability": "medium"},
        first_seen_at=datetime.now(timezone.utc),
        last_seen_at=datetime.now(timezone.utc),
        occurrence_count=3,
        severity="medium",
    )
    link = SessionSignatureModel(session_id=session_id, signature_id=sig_id, matched_nodes=[])
    db_session.add_all([s, sig, link])
    db_session.commit()

    list_resp = client.get("/api/sessions", headers=auth_headers)
    assert list_resp.status_code == 200
    item = next(i for i in list_resp.json()["items"] if i["id"] == str(session_id))
    assert item["recurrence_level"] == "recurring"
    assert item["recurrence_probability"] == "medium"
    assert item["recurrence_count"] == 3

    detail_resp = client.get(f"/api/sessions/{session_id}", headers=auth_headers)
    assert detail_resp.status_code == 200
    detail = detail_resp.json()
    assert detail["recurrence_level"] == "recurring"
    assert detail["recurrence_probability"] == "medium"
    assert detail["recurrence_count"] == 3


def test_get_session_not_found(client, auth_headers):
    response = client.get(f"/api/sessions/{uuid.uuid4()}", headers=auth_headers)
    assert response.status_code == 404
