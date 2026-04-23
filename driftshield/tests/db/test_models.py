import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from driftshield.db.models import (
    AnalystValidationModel,
    Base,
    DecisionNodeModel,
    ForensicCaseModel,
    ReportModel,
    SessionModel,
)


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def test_create_session_model(db_session):
    session_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    s = SessionModel(
        id=session_id,
        external_id="ext-123",
        agent_id="claude-code",
        started_at=now,
        status="completed",
        metadata_json={"source": "test"},
    )
    db_session.add(s)
    db_session.commit()

    loaded = db_session.get(SessionModel, session_id)
    assert loaded is not None
    assert loaded.external_id == "ext-123"
    assert loaded.agent_id == "claude-code"
    assert loaded.status == "completed"
    assert loaded.metadata_json == {"source": "test"}


def test_session_model_defaults(db_session):
    s = SessionModel(
        id=uuid.uuid4(),
        started_at=datetime.now(timezone.utc),
        status="running",
    )
    db_session.add(s)
    db_session.commit()
    assert s.external_id is None
    assert s.agent_id is None
    assert s.metadata_json is None


def test_create_decision_node(db_session):
    session_id = uuid.uuid4()
    s = SessionModel(id=session_id, started_at=datetime.now(timezone.utc), status="completed")
    db_session.add(s)
    db_session.flush()

    node_id = uuid.uuid4()
    node = DecisionNodeModel(
        id=node_id,
        session_id=session_id,
        parent_node_id=None,
        sequence_num=1,
        timestamp=datetime.now(timezone.utc),
        event_type="TOOL_CALL",
        action="read_file",
        inputs={"path": "/etc/config"},
        outputs={"content": "..."},
        assumption_mutation=False,
        policy_divergence=False,
        constraint_violation=False,
        context_contamination=False,
        coverage_gap=True,
        is_inflection_node=False,
    )
    db_session.add(node)
    db_session.commit()

    loaded = db_session.get(DecisionNodeModel, node_id)
    assert loaded is not None
    assert loaded.session_id == session_id
    assert loaded.event_type == "TOOL_CALL"
    assert loaded.coverage_gap is True
    assert loaded.assumption_mutation is False


def test_create_decision_node_with_explanations(db_session):
    session_id = uuid.uuid4()
    db_session.add(
        SessionModel(
            id=session_id,
            started_at=datetime.now(timezone.utc),
            status="completed",
        )
    )
    db_session.flush()

    node_id = uuid.uuid4()
    db_session.add(
        DecisionNodeModel(
            id=node_id,
            session_id=session_id,
            sequence_num=1,
            timestamp=datetime.now(timezone.utc),
            event_type="TOOL_CALL",
            action="review_sections",
            coverage_gap=True,
            risk_explanations={
                "coverage_gap": {
                    "reason": "Output referenced fewer items than were provided in the input.",
                    "confidence": 0.86,
                    "evidence_refs": ["inputs.sections", "outputs.reviewed_sections"],
                }
            },
            is_inflection_node=True,
            inflection_explanation={
                "reason": "Selected as the inflection point because it is the closest flagged node on the path to the failure node.",
                "confidence": 1.0,
                "evidence_refs": [f"node:{node_id}", "risk:coverage_gap"],
            },
        )
    )
    db_session.commit()

    loaded = db_session.get(DecisionNodeModel, node_id)
    assert loaded is not None
    assert loaded.risk_explanations == {
        "coverage_gap": {
            "reason": "Output referenced fewer items than were provided in the input.",
            "confidence": 0.86,
            "evidence_refs": ["inputs.sections", "outputs.reviewed_sections"],
        }
    }
    assert loaded.inflection_explanation == {
        "reason": "Selected as the inflection point because it is the closest flagged node on the path to the failure node.",
        "confidence": 1.0,
        "evidence_refs": [f"node:{node_id}", "risk:coverage_gap"],
    }


def test_decision_node_parent_child(db_session):
    session_id = uuid.uuid4()
    s = SessionModel(id=session_id, started_at=datetime.now(timezone.utc), status="completed")
    db_session.add(s)
    db_session.flush()

    now = datetime.now(timezone.utc)
    parent = DecisionNodeModel(
        id=uuid.uuid4(), session_id=session_id, sequence_num=1,
        timestamp=now, event_type="TOOL_CALL", action="start",
    )
    child = DecisionNodeModel(
        id=uuid.uuid4(), session_id=session_id, parent_node_id=parent.id,
        sequence_num=2, timestamp=now, event_type="TOOL_CALL", action="next",
    )
    db_session.add_all([parent, child])
    db_session.commit()

    loaded_child = db_session.get(DecisionNodeModel, child.id)
    assert loaded_child.parent_node_id == parent.id


def test_oss_metadata_omits_private_recurrence_tables():
    assert "recurrence_signatures" not in Base.metadata.tables
    assert "session_signatures" not in Base.metadata.tables


def test_create_report(db_session):
    session_id = uuid.uuid4()
    s = SessionModel(id=session_id, started_at=datetime.now(timezone.utc), status="completed")
    db_session.add(s)
    db_session.flush()

    report_id = uuid.uuid4()
    report = ReportModel(
        id=report_id,
        session_id=session_id,
        generated_at=datetime.now(timezone.utc),
        report_type="full",
        content_markdown="# Report\n\nSample report content.",
        content_json={"sections": []},
        generated_by="system",
    )
    db_session.add(report)
    db_session.commit()

    loaded = db_session.get(ReportModel, report_id)
    assert loaded is not None
    assert loaded.session_id == session_id
    assert loaded.report_type == "full"
    assert "Sample report content" in loaded.content_markdown
    assert loaded.content_json == {"sections": []}


def test_create_forensic_case(db_session):
    session_id = uuid.uuid4()
    report_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    db_session.add(
        SessionModel(
            id=session_id,
            started_at=now,
            status="completed",
        )
    )
    db_session.add(
        ReportModel(
            id=report_id,
            session_id=session_id,
            generated_at=now,
            report_type="summary",
            content_markdown="# Report",
            content_json={"sections": []},
            generated_by="system",
        )
    )
    db_session.flush()

    case_id = uuid.uuid4()
    db_session.add(
        ForensicCaseModel(
            id=case_id,
            session_id=session_id,
            report_id=report_id,
            state="reported",
            artifact_refs=[
                {
                    "ref_id": f"session:{session_id}",
                    "kind": "analysis_session",
                    "role": "session",
                    "target_ref": str(session_id),
                }
            ],
            review_refs=[],
            audit_refs=[],
            created_at=now,
            updated_at=now,
        )
    )
    db_session.commit()

    loaded = db_session.get(ForensicCaseModel, case_id)
    assert loaded is not None
    assert loaded.session_id == session_id
    assert loaded.report_id == report_id
    assert loaded.state == "reported"
    assert loaded.artifact_refs == [
        {
            "ref_id": f"session:{session_id}",
            "kind": "analysis_session",
            "role": "session",
            "target_ref": str(session_id),
        }
    ]


def test_create_analyst_validation(db_session):
    session_id = uuid.uuid4()
    s = SessionModel(id=session_id, started_at=datetime.now(timezone.utc), status="completed")
    db_session.add(s)
    db_session.flush()

    validation_id = uuid.uuid4()
    validation = AnalystValidationModel(
        id=validation_id,
        session_id=session_id,
        target_type="signature",
        target_ref="abc123",
        verdict="accept",
        confidence=0.91,
        reviewer="demo",
        notes="Looks right",
        metadata_json={"signature_hash": "abc123"},
        shareable=True,
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(validation)
    db_session.commit()

    loaded = db_session.get(AnalystValidationModel, validation_id)
    assert loaded is not None
    assert loaded.target_type == "signature"
    assert loaded.verdict == "accept"
    assert loaded.shareable is True
