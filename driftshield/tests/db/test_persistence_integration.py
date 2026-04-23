"""Integration tests that require a running PostgreSQL instance.

Run: docker compose -f docker-compose.dev.yml up -d
Then: RUN_INTEGRATION_TESTS=1 pytest tests/db/test_persistence_integration.py -v
"""
import os
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from driftshield.core.models import (
    CanonicalEvent,
    EventType,
    ExplanationPayload,
    ForensicCaseState,
    RiskClassification,
    Session as DomainSession,
    SessionStatus,
)
from driftshield.core.analysis.session import analyze_session
from driftshield.db.models import Base, ReportModel
from driftshield.db.persistence import PersistenceService

POSTGRES_URL = os.environ.get(
    "DATABASE_URL", "postgresql://drift:drift@localhost:5432/driftshield"
)

pytestmark = pytest.mark.skipif(
    not os.environ.get("RUN_INTEGRATION_TESTS"),
    reason="Set RUN_INTEGRATION_TESTS=1 and start PostgreSQL to run",
)


@pytest.fixture
def pg_session():
    engine = create_engine(POSTGRES_URL)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
        session.rollback()


def test_roundtrip_save_and_load(pg_session):
    session_id = uuid.uuid4()
    event = CanonicalEvent(
        id=uuid.uuid4(),
        session_id=str(session_id),
        timestamp=datetime.now(timezone.utc),
        event_type=EventType.TOOL_CALL,
        agent_id="integration-test",
        action="test_action",
        inputs={"key": "value"},
        outputs={"result": "ok"},
    )
    domain_session = DomainSession(
        id=session_id,
        agent_id="integration-test",
        started_at=datetime.now(timezone.utc),
        status=SessionStatus.COMPLETED,
    )
    result = analyze_session([event])
    service = PersistenceService(pg_session)
    service.save(domain_session, result)
    pg_session.commit()

    loaded = service.load_session(session_id)
    assert loaded is not None
    assert loaded.agent_id == "integration-test"

    graph = service.load_graph(session_id)
    assert len(graph.nodes) == 1
    assert graph.nodes[0].action == "test_action"


def test_roundtrip_save_and_load_explanations(pg_session):
    session_id = uuid.uuid4()
    event = CanonicalEvent(
        id=uuid.uuid4(),
        session_id=str(session_id),
        timestamp=datetime.now(timezone.utc),
        event_type=EventType.TOOL_CALL,
        agent_id="integration-test",
        action="review_sections",
        inputs={"sections": ["intro", "body", "appendix"]},
        outputs={"reviewed_sections": ["intro", "body"]},
        risk_classification=RiskClassification(
            coverage_gap=True,
            explanations={
                "coverage_gap": ExplanationPayload(
                    reason="Output referenced fewer items than were provided in the input.",
                    confidence=0.86,
                    evidence_refs=["inputs.sections", "outputs.reviewed_sections"],
                )
            },
        ),
    )
    domain_session = DomainSession(
        id=session_id,
        agent_id="integration-test",
        started_at=datetime.now(timezone.utc),
        status=SessionStatus.COMPLETED,
    )
    result = analyze_session([event])
    service = PersistenceService(pg_session)
    service.save(domain_session, result)
    pg_session.commit()

    row = pg_session.execute(
        text("SELECT risk_explanations, inflection_explanation FROM decision_nodes WHERE session_id = :session_id"),
        {"session_id": session_id},
    ).one()
    assert row.risk_explanations["coverage_gap"]["reason"] == "Output referenced fewer items than were provided in the input."
    assert row.inflection_explanation["reason"] == "Selected as the inflection point using weighted scoring across severity, compounding risk, recovery opportunity, and point-of-no-return behaviour."

    graph = service.load_graph(session_id)
    assert graph is not None
    assert graph.nodes[0].event.risk_classification is not None
    assert graph.nodes[0].event.risk_classification.explanations["coverage_gap"] == ExplanationPayload(
        reason="Output referenced fewer items than were provided in the input.",
        confidence=0.86,
        evidence_refs=["inputs.sections", "outputs.reviewed_sections"],
    )


def test_roundtrip_save_and_load_forensic_case(pg_session):
    session_id = uuid.uuid4()
    event = CanonicalEvent(
        id=uuid.uuid4(),
        session_id=str(session_id),
        timestamp=datetime.now(timezone.utc),
        event_type=EventType.TOOL_CALL,
        agent_id="integration-test",
        action="read_file",
        inputs={"path": "/tmp/integration-evidence.txt"},
        outputs={"content": "captured"},
    )
    domain_session = DomainSession(
        id=session_id,
        agent_id="integration-test",
        started_at=datetime.now(timezone.utc),
        status=SessionStatus.COMPLETED,
    )
    result = analyze_session([event])
    service = PersistenceService(pg_session)
    service.save(domain_session, result)

    report = ReportModel(
        id=uuid.uuid4(),
        session_id=session_id,
        generated_at=datetime.now(timezone.utc),
        report_type="full",
        content_markdown="# Report",
        content_json={"sections": []},
        generated_by="integration-test",
    )
    pg_session.add(report)
    pg_session.flush()
    service.upsert_forensic_case(domain_session, result, report=report)
    pg_session.commit()

    case = service.load_case_for_session(session_id)

    assert case is not None
    assert case.state is ForensicCaseState.REPORTED
    assert case.report_id == report.id
    assert any(
        ref.role == "event_artifact"
        and ref.metadata == {
            "kind": "path",
            "value": "/tmp/integration-evidence.txt",
            "source": "inputs",
        }
        for ref in case.artifact_refs
    )
