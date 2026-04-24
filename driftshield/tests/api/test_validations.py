import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session as DBSession
from sqlalchemy.pool import StaticPool

from driftshield.api.app import create_app
from driftshield.db.models import Base, ReportModel, SessionModel


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
    db_session.add(
        SessionModel(
            id=session_id,
            agent_id="test-agent",
            started_at=datetime.now(timezone.utc),
            status="completed",
        )
    )
    db_session.commit()
    return session_id


@pytest.fixture
def seeded_report(db_session, seeded_session):
    report_id = uuid.uuid4()
    db_session.add(
        ReportModel(
            id=report_id,
            session_id=seeded_session,
            generated_at=datetime.now(timezone.utc),
            report_type="full",
            content_markdown="# Report",
            content_json={
                "classification": "Multiple visible risk points (2 flagged events).",
                "candidate_break_point": {
                    "status": "identified",
                    "summary": "Visible break point at event #2.",
                },
                "findings": [
                    {
                        "finding_id": f"finding:candidate_break_point:{seeded_session}",
                        "finding_kind": "candidate_break_point",
                    },
                    {
                        "finding_id": f"finding:evidence_gap:{seeded_session}",
                        "finding_kind": "evidence_gap",
                    }
                ],
                "pattern_matches": [
                    {
                        "match_id": "pattern_match:session-1:0",
                        "family_id": "coverage_gap",
                    }
                ],
            },
            generated_by="system",
        )
    )
    db_session.commit()
    return report_id


def test_create_and_list_validations(client, auth_headers, seeded_session):
    payload = {
        "target_type": "risk_flag",
        "target_ref": f"{uuid.uuid4()}:coverage_gap",
        "verdict": "accept",
        "reviewer": "demo",
        "confidence": 0.87,
        "notes": "Looks correct",
        "metadata_json": {
            "node_id": str(uuid.uuid4()),
            "flag_name": "coverage_gap",
            "review_outcome": {"label": "useful_failure", "target_type": "risk_flag"},
        },
        "shareable": True,
    }

    post = client.post(
        f"/api/sessions/{seeded_session}/validations",
        headers=auth_headers,
        json=payload,
    )
    assert post.status_code == 200
    created = post.json()
    assert created["target_type"] == "risk_flag"
    assert created["verdict"] == "accept"
    assert created["metadata_json"]["review_outcome"]["label"] == "useful_failure"

    get_resp = client.get(
        f"/api/sessions/{seeded_session}/validations",
        headers=auth_headers,
    )
    assert get_resp.status_code == 200
    rows = get_resp.json()
    assert len(rows) == 1
    assert rows[0]["reviewer"] == "demo"


def test_create_validation_rejects_invalid_review_outcome(client, auth_headers, seeded_session):
    payload = {
        "target_type": "inflection",
        "target_ref": str(uuid.uuid4()),
        "verdict": "accept",
        "reviewer": "devin",
        "metadata_json": {
            "review_outcome": {"label": "definitely_not_real"},
        },
    }
    resp = client.post(
        f"/api/sessions/{seeded_session}/validations",
        headers=auth_headers,
        json=payload,
    )
    assert resp.status_code == 400
    assert "review_outcome.label" in resp.json()["detail"]




def test_create_validation_accepts_null_metadata_json(client, auth_headers, seeded_session):
    payload = {
        "target_type": "inflection",
        "target_ref": str(uuid.uuid4()),
        "verdict": "accept",
        "reviewer": "devin",
        "metadata_json": None,
    }
    resp = client.post(
        f"/api/sessions/{seeded_session}/validations",
        headers=auth_headers,
        json=payload,
    )
    assert resp.status_code == 200
    assert resp.json()["metadata_json"] is None


def test_create_validation_rejects_non_object_review_outcome(client, auth_headers, seeded_session):
    payload = {
        "target_type": "inflection",
        "target_ref": str(uuid.uuid4()),
        "verdict": "accept",
        "reviewer": "devin",
        "metadata_json": {
            "review_outcome": "useful_failure",
        },
    }
    resp = client.post(
        f"/api/sessions/{seeded_session}/validations",
        headers=auth_headers,
        json=payload,
    )
    assert resp.status_code == 400
    assert "review_outcome metadata must be an object" in resp.json()["detail"]


def test_create_validation_rejects_contradictory_review_outcome_verdict(client, auth_headers, seeded_session):
    payload = {
        "target_type": "risk_flag",
        "target_ref": f"{uuid.uuid4()}:coverage_gap",
        "verdict": "reject",
        "reviewer": "devin",
        "metadata_json": {
            "review_outcome": {"label": "useful_failure", "target_type": "risk_flag"},
        },
    }
    resp = client.post(
        f"/api/sessions/{seeded_session}/validations",
        headers=auth_headers,
        json=payload,
    )
    assert resp.status_code == 400
    assert "requires verdict 'accept'" in resp.json()["detail"]

def test_create_validation_for_missing_session_returns_404(client, auth_headers):
    payload = {
        "target_type": "inflection",
        "target_ref": str(uuid.uuid4()),
        "verdict": "accept",
        "reviewer": "devin",
    }
    resp = client.post(
        f"/api/sessions/{uuid.uuid4()}/validations",
        headers=auth_headers,
        json=payload,
    )
    assert resp.status_code == 404


def test_create_and_list_forensic_feedback(client, auth_headers, seeded_session, seeded_report):
    payload = {
        "target_kind": "pattern_match",
        "target_ref": "pattern_match:session-1:0",
        "category": "failure_family",
        "outcome": "different_family",
        "reviewer": "demo",
        "report_id": str(seeded_report),
        "confidence": 0.64,
        "suggested_failure_family": "verification_failure",
        "problem_detail": "visible failure fits verification output better",
        "notes": "Bounded review note",
    }

    post = client.post(
        f"/api/sessions/{seeded_session}/forensic-feedback",
        headers=auth_headers,
        json=payload,
    )
    assert post.status_code == 201
    created = post.json()
    assert created["target_kind"] == "pattern_match"
    assert created["category"] == "failure_family"
    assert created["outcome"] == "different_family"
    assert created["verdict"] == "reject"
    assert created["report_id"] == str(seeded_report)
    assert created["suggested_failure_family"] == "verification_failure"

    get_resp = client.get(
        f"/api/sessions/{seeded_session}/forensic-feedback",
        headers=auth_headers,
        params={"report_id": str(seeded_report)},
    )
    assert get_resp.status_code == 200
    rows = get_resp.json()
    assert len(rows) == 1
    assert rows[0]["id"] == created["id"]


def test_create_forensic_feedback_rejects_unknown_report_target(
    client,
    auth_headers,
    seeded_session,
    seeded_report,
):
    payload = {
        "target_kind": "pattern_match",
        "target_ref": "pattern_match:missing",
        "category": "failure_family",
        "outcome": "different_family",
        "reviewer": "demo",
        "report_id": str(seeded_report),
        "suggested_failure_family": "verification_failure",
    }

    resp = client.post(
        f"/api/sessions/{seeded_session}/forensic-feedback",
        headers=auth_headers,
        json=payload,
    )

    assert resp.status_code == 422
    assert "Pattern match target_ref not found" in resp.json()["detail"]


def test_create_forensic_feedback_requires_report_for_report_scoped_target(
    client,
    auth_headers,
    seeded_session,
):
    payload = {
        "target_kind": "pattern_match",
        "target_ref": "pattern_match:session-1:0",
        "category": "failure_family",
        "outcome": "different_family",
        "reviewer": "demo",
        "suggested_failure_family": "verification_failure",
    }

    resp = client.post(
        f"/api/sessions/{seeded_session}/forensic-feedback",
        headers=auth_headers,
        json=payload,
    )

    assert resp.status_code == 422
    assert "report_id is required for pattern_match feedback" in resp.json()["detail"]


def test_create_forensic_feedback_validates_evidence_gap_target(
    client,
    auth_headers,
    seeded_session,
    seeded_report,
):
    payload = {
        "target_kind": "evidence_gap",
        "target_ref": f"finding:evidence_gap:{seeded_session}",
        "category": "evidence",
        "outcome": "missing",
        "reviewer": "demo",
        "report_id": str(seeded_report),
        "problem_detail": "The report should cite the failed tool result.",
    }

    resp = client.post(
        f"/api/sessions/{seeded_session}/forensic-feedback",
        headers=auth_headers,
        json=payload,
    )

    assert resp.status_code == 201
    assert resp.json()["target_kind"] == "evidence_gap"
    assert resp.json()["verdict"] == "reject"


def test_create_forensic_feedback_rejects_vague_family_redirect(
    client,
    auth_headers,
    seeded_session,
    seeded_report,
):
    payload = {
        "target_kind": "pattern_match",
        "target_ref": "pattern_match:session-1:0",
        "category": "failure_family",
        "outcome": "different_family",
        "reviewer": "demo",
        "report_id": str(seeded_report),
    }

    resp = client.post(
        f"/api/sessions/{seeded_session}/forensic-feedback",
        headers=auth_headers,
        json=payload,
    )

    assert resp.status_code == 400
    assert "suggested_failure_family is required" in resp.json()["detail"]
