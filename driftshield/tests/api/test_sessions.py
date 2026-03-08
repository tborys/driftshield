import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session as DBSession
from sqlalchemy.pool import StaticPool

from driftshield.api.app import create_app
from driftshield.db.models import (
    AnalystValidationModel,
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


def test_graph_endpoint_returns_risk_and_inflection_explanations(client, auth_headers, db_session):
    session_id = uuid.uuid4()
    node_id = uuid.uuid4()
    db_session.add(
        SessionModel(
            id=session_id,
            agent_id="test-agent",
            started_at=datetime.now(timezone.utc),
            status="completed",
        )
    )
    db_session.add(
        DecisionNodeModel(
            id=node_id,
            session_id=session_id,
            sequence_num=1,
            event_type="TOOL_CALL",
            action="review_sections",
            coverage_gap=True,
            is_inflection_node=True,
            risk_explanations={
                "coverage_gap": {
                    "reason": "Output referenced fewer items than were provided in the input.",
                    "confidence": 0.86,
                    "evidence_refs": ["inputs.sections", "outputs.reviewed_sections"],
                }
            },
            inflection_explanation={
                "reason": "Selected as the inflection point because it is the closest flagged node on the path to the failure node.",
                "confidence": 1.0,
                "evidence_refs": [f"node:{node_id}", "risk:coverage_gap"],
            },
        )
    )
    db_session.commit()

    response = client.get(f"/api/sessions/{session_id}/graph", headers=auth_headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["nodes"][0]["risk_flags"] == ["coverage_gap"]
    assert payload["nodes"][0]["risk_explanations"] == {
        "coverage_gap": {
            "reason": "Output referenced fewer items than were provided in the input.",
            "confidence": 0.86,
            "evidence_refs": ["inputs.sections", "outputs.reviewed_sections"],
        }
    }
    assert payload["nodes"][0]["inflection_explanation"] == {
        "reason": "Selected as the inflection point because it is the closest flagged node on the path to the failure node.",
        "confidence": 1.0,
        "evidence_refs": [f"node:{node_id}", "risk:coverage_gap"],
    }


def test_create_session_validation_and_list_for_node(client, auth_headers, seeded_session, db_session):
    node = (
        db_session.query(DecisionNodeModel)
        .filter(DecisionNodeModel.session_id == seeded_session)
        .order_by(DecisionNodeModel.sequence_num.asc())
        .first()
    )
    assert node is not None

    payload = {
        "target_type": "risk_flag",
        "target_ref": f"{node.id}:coverage_gap",
        "verdict": "accept",
        "reviewer": "analyst",
        "confidence": 0.8,
        "notes": "Looks correct",
        "shareable": False,
    }

    create_response = client.post(
        f"/api/sessions/{seeded_session}/validations",
        headers=auth_headers,
        json=payload,
    )
    assert create_response.status_code == 200
    created = create_response.json()
    assert created["target_ref"] == payload["target_ref"]
    assert created["reviewer"] == "analyst"

    list_response = client.get(
        f"/api/sessions/{seeded_session}/validations",
        headers=auth_headers,
    )
    assert list_response.status_code == 200
    listed = list_response.json()
    assert len(listed) == 1
    assert listed[0]["target_ref"] == payload["target_ref"]

    db_row = db_session.query(AnalystValidationModel).first()
    assert db_row is not None
    assert db_row.target_ref == payload["target_ref"]
    assert db_row.verdict == "accept"


def test_create_session_validation_for_missing_session_returns_404(client, auth_headers):
    payload = {
        "target_type": "risk_flag",
        "target_ref": f"{uuid.uuid4()}:coverage_gap",
        "verdict": "accept",
        "reviewer": "analyst",
        "confidence": 0.8,
    }

    response = client.post(
        f"/api/sessions/{uuid.uuid4()}/validations",
        headers=auth_headers,
        json=payload,
    )

    assert response.status_code == 404
