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
from driftshield.core.analysis.session import analyze_session
from driftshield.core.models import (
    CanonicalEvent,
    EventType,
    ForensicCaseState,
    RiskClassification,
    Session as DomainSession,
    SessionStatus,
)
from driftshield.db.models import Base, DecisionNodeModel, ForensicCaseModel, ReportModel, SessionModel
from driftshield.db.persistence import PersistenceService


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
    lines = [
        {
            "sessionId": "forensic-workflow-session-123",
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tool_1",
                        "name": "Read",
                        "input": {"file_path": "/tmp/evidence.txt"},
                    }
                ]
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
        {
            "sessionId": "forensic-workflow-session-123",
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "tool_1",
                        "content": "contents",
                    }
                ]
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    ]
    return "\n".join(json.dumps(line) for line in lines).encode()


@pytest.fixture
def seeded_session(db_session):
    session_id = uuid.uuid4()
    s = SessionModel(
        id=session_id, agent_id="test", started_at=datetime.now(timezone.utc), status="completed"
    )
    node = DecisionNodeModel(
        id=uuid.uuid4(), session_id=session_id, sequence_num=1,
        event_type="TOOL_CALL", action="test",
    )
    db_session.add_all([s, node])
    db_session.commit()
    return session_id


def test_generate_report(client, auth_headers, seeded_session):
    response = client.post(
        f"/api/sessions/{seeded_session}/report",
        headers=auth_headers,
        json={"report_type": "full"},
    )
    assert response.status_code == 201
    data = response.json()
    assert "id" in data
    assert data["report_type"] == "full"


def test_generate_report_rejects_unknown_report_type(client, auth_headers, seeded_session):
    response = client.post(
        f"/api/sessions/{seeded_session}/report",
        headers=auth_headers,
        json={"report_type": "unknown"},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Unsupported report type: unknown"


def test_generate_forensic_report_from_transcript_returns_forensic_contract(
    client,
    auth_headers,
    sample_transcript,
):
    response = client.post(
        "/api/forensics/report",
        headers=auth_headers,
        files={"file": ("sample.jsonl", io.BytesIO(sample_transcript), "application/jsonl")},
        data={"format": "claude_code", "report_type": "summary"},
    )

    assert response.status_code == 201

    data = response.json()
    assert data["ingest_status"] == "created"
    assert data["deduplicated"] is False
    assert data["parser_name"] == "claude_code"
    assert data["report"]["report_type"] == "summary"
    assert data["report"]["content_json"]["schema_version"] == "forensic_report.v1"
    assert data["report"]["content_json"]["summary"]["what_happened"]
    assert data["forensic_case"]["state"] == "reported"
    assert data["forensic_case"]["report_id"] == data["report"]["id"]


def test_generate_forensic_report_rejects_unknown_report_type_without_ingesting(
    client,
    auth_headers,
    sample_transcript,
    db_session,
):
    response = client.post(
        "/api/forensics/report",
        headers=auth_headers,
        files={"file": ("sample.jsonl", io.BytesIO(sample_transcript), "application/jsonl")},
        data={"format": "claude_code", "report_type": "unknown"},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Unsupported report type: unknown"
    assert db_session.query(SessionModel).count() == 0
    assert db_session.query(ReportModel).count() == 0


def test_generate_forensic_report_reuses_session_for_duplicate_upload(
    client,
    auth_headers,
    sample_transcript,
    db_session,
):
    first = client.post(
        "/api/forensics/report",
        headers=auth_headers,
        files={"file": ("sample.jsonl", io.BytesIO(sample_transcript), "application/jsonl")},
        data={"format": "claude_code", "report_type": "full"},
    )
    second = client.post(
        "/api/forensics/report",
        headers=auth_headers,
        files={"file": ("sample.jsonl", io.BytesIO(sample_transcript), "application/jsonl")},
        data={"format": "claude_code", "report_type": "full"},
    )

    assert first.status_code == 201
    assert second.status_code == 200

    first_data = first.json()
    second_data = second.json()
    assert second_data["deduplicated"] is True
    assert second_data["ingest_status"] == "deduped"
    assert second_data["session_id"] == first_data["session_id"]
    assert second_data["report"]["id"] == first_data["report"]["id"]

    assert db_session.query(SessionModel).count() == 1
    assert db_session.query(ReportModel).count() == 1


def test_generate_forensic_report_rolls_back_ingest_when_report_build_fails(
    client,
    auth_headers,
    sample_transcript,
    db_session,
    monkeypatch,
):
    def fail_build(self, session, result, report_type):
        raise RuntimeError("report builder failed")

    emit_calls = []

    def fake_record_analysis_event(self, **kwargs):
        emit_calls.append(kwargs)
        return True

    monkeypatch.setattr("driftshield.api.routes.reports.ReportBuilder.build", fail_build)
    monkeypatch.setattr(
        "driftshield.api.ingest_workflow.TelemetryService.record_analysis_event",
        fake_record_analysis_event,
    )

    with pytest.raises(RuntimeError, match="report builder failed"):
        client.post(
            "/api/forensics/report",
            headers=auth_headers,
            files={"file": ("sample.jsonl", io.BytesIO(sample_transcript), "application/jsonl")},
            data={"format": "claude_code", "report_type": "summary"},
        )

    assert db_session.query(SessionModel).count() == 0
    assert db_session.query(DecisionNodeModel).count() == 0
    assert db_session.query(ForensicCaseModel).count() == 0
    assert db_session.query(ReportModel).count() == 0
    assert emit_calls == []


def test_list_reports_for_session(client, auth_headers, seeded_session, db_session):
    report = ReportModel(
        id=uuid.uuid4(),
        session_id=seeded_session,
        generated_at=datetime.now(timezone.utc),
        report_type="full",
        content_markdown="# Report",
        generated_by="test",
    )
    db_session.add(report)
    db_session.commit()

    response = client.get(f"/api/sessions/{seeded_session}/reports", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1


def test_get_report_by_id(client, auth_headers, seeded_session, db_session):
    report_id = uuid.uuid4()
    report = ReportModel(
        id=report_id,
        session_id=seeded_session,
        generated_at=datetime.now(timezone.utc),
        report_type="full",
        content_markdown="# Test Report",
        content_json={"sections": []},
        generated_by="test",
    )
    db_session.add(report)
    db_session.commit()

    response = client.get(f"/api/reports/{report_id}", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["content_markdown"] == "# Test Report"


def test_get_report_not_found(client, auth_headers):
    response = client.get(f"/api/reports/{uuid.uuid4()}", headers=auth_headers)
    assert response.status_code == 404


def test_generated_report_has_real_content(client, auth_headers, seeded_session, db_session):
    response = client.post(
        f"/api/sessions/{seeded_session}/report",
        headers=auth_headers,
        json={"report_type": "full"},
    )
    assert response.status_code == 201
    report_id = response.json()["id"]

    # Fetch the report and check it has real content
    get_response = client.get(f"/api/reports/{report_id}", headers=auth_headers)
    data = get_response.json()
    assert "Forensic Analysis Report" in data["content_markdown"]
    assert data["content_json"]["sections"] is not None
    assert len(data["content_json"]["sections"]) == 4
    assert data["content_json"]["schema_version"] == "forensic_report.v1"
    assert data["content_json"]["summary"]["what_happened"]
    assert data["content_json"]["findings"]
    assert data["content_json"]["evidence_index"]
    assert data["content_json"]["candidate_break_point"]["status"] == "no_clear_break_point"
    assert "recurrence_probability" not in data["content_json"]


def test_generate_report_updates_forensic_case_without_losing_saved_evidence_artifacts(
    client,
    auth_headers,
    db_session,
):
    session_id = uuid.uuid4()
    event = CanonicalEvent(
        id=uuid.uuid4(),
        session_id=str(session_id),
        timestamp=datetime.now(timezone.utc),
        event_type=EventType.TOOL_CALL,
        agent_id="test-agent",
        action="read_file",
        inputs={"path": "/tmp/evidence.txt"},
        outputs={"content": "evidence"},
    )
    domain_session = DomainSession(
        id=session_id,
        agent_id="test-agent",
        started_at=datetime.now(timezone.utc),
        status=SessionStatus.COMPLETED,
    )
    service = PersistenceService(db_session)
    service.save(domain_session, analyze_session([event]))
    db_session.commit()

    response = client.post(
        f"/api/sessions/{session_id}/report",
        headers=auth_headers,
        json={"report_type": "full"},
    )

    assert response.status_code == 201

    case = service.load_case_for_session(session_id)
    assert case is not None
    assert case.state is ForensicCaseState.REPORTED
    assert case.report_id == uuid.UUID(response.json()["id"])
    assert any(
        ref.role == "event_artifact"
        and ref.metadata == {"kind": "path", "value": "/tmp/evidence.txt", "source": "inputs"}
        for ref in case.artifact_refs
    )


def test_generate_report_preserves_legacy_inflection_fields_for_uncertain_break_points(
    client,
    auth_headers,
    db_session,
):
    session_id = uuid.uuid4()
    events = [
        CanonicalEvent(
            id=uuid.uuid4(),
            session_id=str(session_id),
            timestamp=datetime.now(timezone.utc),
            event_type=EventType.TOOL_CALL,
            agent_id="test-agent",
            action="early_policy_drift",
            risk_classification=RiskClassification(policy_divergence=True),
        ),
        CanonicalEvent(
            id=uuid.uuid4(),
            session_id=str(session_id),
            timestamp=datetime.now(timezone.utc),
            event_type=EventType.TOOL_CALL,
            agent_id="test-agent",
            action="later_constraint_drift",
            parent_event_id=None,
            risk_classification=RiskClassification(constraint_violation=True),
        ),
        CanonicalEvent(
            id=uuid.uuid4(),
            session_id=str(session_id),
            timestamp=datetime.now(timezone.utc),
            event_type=EventType.OUTPUT,
            agent_id="test-agent",
            action="failure",
        ),
    ]
    events[1].parent_event_id = events[0].id
    events[1].parent_event_refs = [events[0].id]
    events[2].parent_event_id = events[1].id
    events[2].parent_event_refs = [events[1].id]
    domain_session = DomainSession(
        id=session_id,
        agent_id="test-agent",
        started_at=datetime.now(timezone.utc),
        status=SessionStatus.COMPLETED,
    )
    service = PersistenceService(db_session)
    service.save(domain_session, analyze_session(events))
    db_session.commit()

    response = client.post(
        f"/api/sessions/{session_id}/report",
        headers=auth_headers,
        json={"report_type": "full"},
    )

    assert response.status_code == 201

    report = db_session.get(ReportModel, uuid.UUID(response.json()["id"]))
    assert report is not None
    assert report.content_json["candidate_break_point"]["status"] == "no_clear_break_point"
    assert report.content_json["inflection_node_id"] is not None


def test_generate_report_projects_legacy_family_only_signature_summary(
    client,
    auth_headers,
    db_session,
):
    session_id = uuid.uuid4()
    db_session.add(
        SessionModel(
            id=session_id,
            agent_id="legacy-agent",
            started_at=datetime.now(timezone.utc),
            status="completed",
            metadata_json={
                "signature_summary": {
                    "status": "matched",
                    "primary_family_id": "coverage_gap",
                    "matched_family_ids": ["coverage_gap", "verification_failure"],
                    "match_count": 2,
                    "summary": "Matched two known failure families.",
                }
            },
        )
    )
    db_session.add_all(
        [
            DecisionNodeModel(
                id=uuid.uuid4(),
                session_id=session_id,
                sequence_num=1,
                event_type="TOOL_CALL",
                action="review",
                coverage_gap=True,
            ),
            DecisionNodeModel(
                id=uuid.uuid4(),
                session_id=session_id,
                sequence_num=2,
                event_type="OUTPUT",
                action="deliver",
            ),
        ]
    )
    db_session.commit()

    response = client.post(
        f"/api/sessions/{session_id}/report",
        headers=auth_headers,
        json={"report_type": "full"},
    )

    assert response.status_code == 201

    report = db_session.get(ReportModel, uuid.UUID(response.json()["id"]))
    assert report is not None
    assert [match["mechanism_id"] for match in report.content_json["pattern_matches"]] == [
        "coverage_gap",
        "verification_failure",
    ]
    assert report.content_json["pattern_matches"][0]["signature_id"] == "mechanism:coverage_gap"


def test_generate_report_ignores_signature_only_payload_without_family_fields(
    client,
    auth_headers,
    db_session,
):
    session_id = uuid.uuid4()
    db_session.add(
        SessionModel(
            id=session_id,
            agent_id="legacy-agent",
            started_at=datetime.now(timezone.utc),
            status="completed",
            metadata_json={
                "signature_summary": {
                    "signature_id": "sig:test",
                    "summary": "Incomplete signature payload without family metadata.",
                }
            },
        )
    )
    db_session.add_all(
        [
            DecisionNodeModel(
                id=uuid.uuid4(),
                session_id=session_id,
                sequence_num=1,
                event_type="TOOL_CALL",
                action="review",
                coverage_gap=True,
            ),
            DecisionNodeModel(
                id=uuid.uuid4(),
                session_id=session_id,
                sequence_num=2,
                event_type="OUTPUT",
                action="deliver",
            ),
        ]
    )
    db_session.commit()

    response = client.post(
        f"/api/sessions/{session_id}/report",
        headers=auth_headers,
        json={"report_type": "full"},
    )

    assert response.status_code == 201

    report = db_session.get(ReportModel, uuid.UUID(response.json()["id"]))
    assert report is not None
    assert report.content_json["pattern_matches"] == []


def test_graveyard_summary_route_is_removed(client, auth_headers):
    response = client.get("/api/graveyard/summary", headers=auth_headers)
    assert response.status_code == 404
