import uuid
from datetime import datetime, timedelta, timezone

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
    SessionModel,
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
        source_session_id="source-session-1",
        source_path="uploads/daily/test-agent.jsonl",
        parser_version="claude_code@1",
        ingested_at=datetime.now(timezone.utc),
        metadata_json={
            "integrity_summary": {
                "integrity_schema_version": "phase3e.v1",
                "trust_band": "trusted",
                "structural_score": 1.0,
                "semantic_score": 0.9,
                "source_factor": 0.95,
                "pattern_integrity_score": 0.95,
                "final_learning_weight": 0.8123,
                "integrity_reasons": ["pattern_integrity_placeholder_oss_v1"],
                "requires_review": False,
                "integrity_evaluated_at": "2026-04-29T07:58:00+00:00",
                "integrity_policy_version": "phase3e.v1.default",
                "evidence_counts": {"total_events": 1, "flagged_events": 1},
                "pattern_integrity_note": "OSS v1 uses a conservative placeholder because private Pattern Object promotion and recurrence logic are out of scope.",
            },
            "integrity_provenance": {
                "source_type": "claude_code",
                "source_session_id": "source-session-1",
                "source_path": "uploads/daily/test-agent.jsonl",
                "parser_version": "claude_code@1",
                "transcript_hash": "abc123",
                "ingested_at": "2026-04-29T07:57:00+00:00",
                "integrity_policy_version": "phase3e.v1.default",
                "integrity_schema_version": "phase3e.v1",
                "integrity_evaluated_at": "2026-04-29T07:58:00+00:00",
                "evidence_counts": {"total_events": 1, "flagged_events": 1},
            },
            "signature_match": {
                "status": "matched",
                "primary_family_id": "coverage_gap",
                "matched_family_ids": ["coverage_gap", "verification_failure"],
                "match_count": 2,
                "summary": "Matched two known failure families.",
            },
            "canonical_analysis": {
                "analysis_session": {
                    "session_id": str(session_id),
                    "analysis_schema_version": "phase-3g-canonical-v1",
                    "source_kind": "claude_code",
                    "parser_version": "claude_code@1",
                    "source_fingerprint": "abc123",
                },
                "normalized_events": [
                    {
                        "event_id": "node-1",
                        "sequence_index": 0,
                        "event_family": "tool_call",
                        "missing_fields": [],
                    }
                ],
                "run_context": {},
                "policy_and_instruction_context": {},
                "expected_vs_actual_delta": {"delta_types": ["missing_required_action"]},
                "extraction_quality_summary": {"overall_quality_band": "usable"},
            },
            "recurrence_status": {
                "status": "recurring",
                "cluster_id": "cluster-42",
                "recurrence_count": 3,
                "summary": "Seen in three related runs.",
            },
        },
    )
    node = DecisionNodeModel(
        id=uuid.uuid4(),
        session_id=session_id,
        sequence_num=1,
        event_type="TOOL_CALL",
        action="read_file",
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
            "evidence_refs": ["risk:coverage_gap"],
        },
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
    assert data["items"][0]["provenance"] == {
        "source_type": "claude_code",
        "source_session_id": "source-session-1",
        "source_path": "uploads/daily/test-agent.jsonl",
        "parser_version": "claude_code@1",
        "transcript_hash": "abc123",
        "ingested_at": data["items"][0]["provenance"]["ingested_at"],
        "integrity_policy_version": "phase3e.v1.default",
        "integrity_schema_version": "phase3e.v1",
        "integrity_evaluated_at": data["items"][0]["provenance"]["integrity_evaluated_at"],
        "evidence_counts": {"total_events": 1, "flagged_events": 1},
    }
    assert data["items"][0]["integrity_status"] == {
        "integrity_schema_version": "phase3e.v1",
        "trust_band": "trusted",
        "structural_score": 1.0,
        "semantic_score": 0.9,
        "source_factor": 0.95,
        "pattern_integrity_score": 0.95,
        "final_learning_weight": 0.8123,
        "integrity_reasons": ["pattern_integrity_placeholder_oss_v1"],
        "requires_review": False,
        "integrity_evaluated_at": data["items"][0]["integrity_status"]["integrity_evaluated_at"],
        "integrity_policy_version": "phase3e.v1.default",
        "evidence_counts": {"total_events": 1, "flagged_events": 1},
        "pattern_integrity_note": "OSS v1 uses a conservative placeholder because private Pattern Object promotion and recurrence logic are out of scope.",
    }
    assert "recurrence_level" not in data["items"][0]


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
    assert data["provenance"]["source_type"] == "claude_code"
    assert data["provenance"]["source_session_id"] == "source-session-1"
    assert data["provenance"]["transcript_hash"] == "abc123"
    assert data["risk_summary"]["coverage_gap"] == 1
    assert data["integrity_status"]["trust_band"] == "trusted"
    assert data["integrity_status"]["final_learning_weight"] == 0.8123
    assert data["integrity_status"]["integrity_reasons"] == ["pattern_integrity_placeholder_oss_v1"]
    assert data["explanations"]["risk_explanations"] == {
        "coverage_gap": [
            {
                "node_id": data["explanations"]["risk_explanations"]["coverage_gap"][0]["node_id"],
                "payload": {
                    "reason": "Output referenced fewer items than were provided in the input.",
                    "confidence": 0.86,
                    "evidence_refs": ["inputs.sections", "outputs.reviewed_sections"],
                },
            }
        ]
    }
    assert data["explanations"]["inflection_explanation"] == {
        "node_id": data["explanations"]["inflection_explanation"]["node_id"],
        "payload": {
            "reason": "Selected as the inflection point because it is the closest flagged node on the path to the failure node.",
            "confidence": 1.0,
            "evidence_refs": ["risk:coverage_gap"],
        },
    }
    assert data["signature_match"] == {
        "status": "matched",
        "primary_mechanism_id": "coverage_gap",
        "matched_mechanism_ids": ["coverage_gap", "verification_failure"],
        "match_count": 2,
        "summary": "Matched two known failure mechanisms from local OSS-safe signals.",
        "raw": {
            "status": "matched",
            "primary_family_id": "coverage_gap",
            "matched_family_ids": ["coverage_gap", "verification_failure"],
            "match_count": 2,
            "summary": "Matched two known failure families.",
        },
    }
    assert data["canonical_analysis"]["analysis_session"]["analysis_schema_version"] == "phase-3g-canonical-v1"
    assert data["canonical_analysis"]["normalized_events"][0]["event_family"] == "tool_call"
    assert data["canonical_analysis"]["expected_vs_actual_delta"]["delta_types"] == ["missing_required_action"]
    assert "recurrence_status" not in data


def test_get_session_detail_falls_back_to_legacy_outcome_status(client, auth_headers, db_session):
    session_id = uuid.uuid4()
    db_session.add(
        SessionModel(
            id=session_id,
            agent_id="legacy-agent",
            started_at=datetime.now(timezone.utc),
            status="completed",
            metadata_json={
                "signature_summary": {
                    "outcome_status": "matched",
                    "primary_family_id": "coverage_gap",
                    "matched_family_ids": ["coverage_gap"],
                    "match_count": 1,
                }
            },
        )
    )
    db_session.add(
        DecisionNodeModel(
            id=uuid.uuid4(),
            session_id=session_id,
            sequence_num=1,
            event_type="TOOL_CALL",
            action="legacy-review",
            coverage_gap=True,
        )
    )
    db_session.commit()

    response = client.get(f"/api/sessions/{session_id}", headers=auth_headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["signature_match"]["status"] == "matched"
    assert payload["signature_match"]["primary_mechanism_id"] == "coverage_gap"
    assert "recurrence_status" not in payload


def test_get_session_detail_keeps_backward_compat_for_missing_integrity_payload(client, auth_headers, db_session):
    session_id = uuid.uuid4()
    db_session.add(
        SessionModel(
            id=session_id,
            agent_id="legacy-agent",
            started_at=datetime.now(timezone.utc),
            status="completed",
            source_session_id="legacy-source",
            source_path="uploads/legacy.jsonl",
            parser_version="claude_code@1",
        )
    )
    db_session.add(
        DecisionNodeModel(
            id=uuid.uuid4(),
            session_id=session_id,
            sequence_num=1,
            event_type="TOOL_CALL",
            action="legacy-review",
        )
    )
    db_session.commit()

    response = client.get(f"/api/sessions/{session_id}", headers=auth_headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["integrity_status"] is None
    assert payload["provenance"]["transcript_hash"] is None


def test_get_session_detail_orders_explanations_by_sequence(client, auth_headers, db_session):
    session_id = uuid.uuid4()
    db_session.add(
        SessionModel(
            id=session_id,
            agent_id="ordered-agent",
            started_at=datetime.now(timezone.utc),
            status="completed",
        )
    )
    db_session.add_all(
        [
            DecisionNodeModel(
                id=uuid.uuid4(),
                session_id=session_id,
                sequence_num=2,
                event_type="TOOL_CALL",
                action="later",
                coverage_gap=True,
                risk_explanations={
                    "coverage_gap": {
                        "reason": "later",
                        "confidence": 0.5,
                        "evidence_refs": [],
                    }
                },
            ),
            DecisionNodeModel(
                id=uuid.uuid4(),
                session_id=session_id,
                sequence_num=1,
                event_type="TOOL_CALL",
                action="earlier",
                coverage_gap=True,
                risk_explanations={
                    "coverage_gap": {
                        "reason": "earlier",
                        "confidence": 0.5,
                        "evidence_refs": [],
                    }
                },
            ),
        ]
    )
    db_session.commit()

    response = client.get(f"/api/sessions/{session_id}", headers=auth_headers)

    assert response.status_code == 200
    explanations = response.json()["explanations"]["risk_explanations"]["coverage_gap"]
    assert [item["payload"]["reason"] for item in explanations] == ["earlier", "later"]


def test_list_sessions_supports_triage_filters(client, auth_headers, db_session):
    now = datetime.now(timezone.utc)
    flagged_session = SessionModel(
        id=uuid.uuid4(),
        agent_id="flagged-agent",
        started_at=now - timedelta(hours=2),
        status="completed",
        source_path="uploads/dogfood/claude-session.jsonl",
        parser_version="claude_code@1",
    )
    unflagged_session = SessionModel(
        id=uuid.uuid4(),
        agent_id="quiet-agent",
        started_at=now - timedelta(days=2),
        status="completed",
        source_path="uploads/dogfood/openai-session.jsonl",
        parser_version="openai@1",
    )
    db_session.add_all([flagged_session, unflagged_session])
    db_session.flush()
    db_session.add(
        DecisionNodeModel(
            id=uuid.uuid4(),
            session_id=flagged_session.id,
            sequence_num=1,
            event_type="TOOL_CALL",
            action="summarise",
            coverage_gap=True,
        )
    )
    db_session.add(
        DecisionNodeModel(
            id=uuid.uuid4(),
            session_id=unflagged_session.id,
            sequence_num=1,
            event_type="OUTPUT",
            action="reply",
        )
    )
    db_session.commit()

    response = client.get(
        "/api/sessions?flagged_only=true&risk_class=coverage_gap&source=claude&since_hours=24",
        headers=auth_headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert [item["id"] for item in payload["items"]] == [str(flagged_session.id)]


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
            source_session_id="source-session-graph",
            source_path="uploads/graph-session.jsonl",
            parser_version="claude_code@1",
            ingested_at=datetime.now(timezone.utc),
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
    assert payload["provenance"] == {
        "source_type": "claude_code",
        "source_session_id": "source-session-graph",
        "source_path": "uploads/graph-session.jsonl",
        "parser_version": "claude_code@1",
        "transcript_hash": None,
        "ingested_at": payload["provenance"]["ingested_at"],
        "integrity_policy_version": None,
        "integrity_schema_version": None,
        "integrity_evaluated_at": None,
        "evidence_counts": {},
    }
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
