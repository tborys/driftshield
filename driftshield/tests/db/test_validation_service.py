import json
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from driftshield.db.models import Base, SessionModel
from driftshield.db.validation_service import ValidationService


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _seed_session(db: Session) -> uuid.UUID:
    session_id = uuid.uuid4()
    db.add(
        SessionModel(
            id=session_id,
            started_at=datetime.now(timezone.utc),
            status="completed",
            agent_id="test-agent",
            source_session_id="dogfood-session-123",
            source_path="fixtures/dogfood/session.jsonl",
            parser_version="openclaw@1",
        )
    )
    db.commit()
    return session_id


def test_record_and_list_validations(db_session):
    session_id = _seed_session(db_session)
    service = ValidationService(db_session)

    service.record_inflection_validation(
        session_id=session_id,
        node_id=uuid.uuid4(),
        verdict="accept",
        reviewer="demo",
        confidence=0.91,
        notes="Correct inflection",
    )
    service.record_risk_flag_validation(
        session_id=session_id,
        node_id=uuid.uuid4(),
        flag_name="coverage_gap",
        verdict="reject",
        reviewer="devin",
        confidence=0.72,
        notes="False positive",
    )

    rows = service.list_validations(session_id=session_id)
    assert len(rows) == 2
    assert {r.target_type for r in rows} == {"inflection", "risk_flag"}


def test_record_validation_accepts_review_outcome_metadata(db_session):
    session_id = _seed_session(db_session)
    service = ValidationService(db_session)
    node_id = uuid.uuid4()

    row = service._record(
        session_id=session_id,
        target_type="risk_flag",
        target_ref=f"{node_id}:coverage_gap",
        verdict="accept",
        reviewer="demo",
        confidence=0.88,
        notes="Confirmed useful failure",
        metadata_json={
            "node_id": str(node_id),
            "flag_name": "coverage_gap",
            "review_outcome": {"label": "useful_failure", "target_type": "risk_flag"},
        },
        shareable=True,
    )

    assert row.metadata_json is not None
    assert row.metadata_json["review_outcome"]["label"] == "useful_failure"


def test_record_forensic_feedback_is_structured_and_retrievable(db_session):
    session_id = _seed_session(db_session)
    report_id = uuid.uuid4()
    service = ValidationService(db_session)

    row = service.record_forensic_feedback(
        session_id=session_id,
        target_kind="pattern_match",
        target_ref="pattern_match:session-1:0",
        category="failure_family",
        outcome="different_family",
        reviewer="demo",
        report_id=report_id,
        confidence=0.67,
        suggested_failure_family="verification_failure",
        problem_detail="visible output fits verification failure better",
    )

    assert row.target_type == "forensic_feedback"
    assert row.verdict == "reject"
    feedback = row.metadata_json["forensic_feedback"]
    assert feedback["schema_version"] == "forensic_feedback.v1"
    assert feedback["target_kind"] == "pattern_match"
    assert feedback["category"] == "failure_family"
    assert feedback["suggested_failure_family"] == "verification_failure"

    rows = service.list_forensic_feedback(session_id=session_id, report_id=report_id)
    assert [item.id for item in rows] == [row.id]


def test_record_forensic_feedback_requires_specific_family_for_redirect(db_session):
    session_id = _seed_session(db_session)
    service = ValidationService(db_session)

    with pytest.raises(ValueError, match="suggested_failure_family is required"):
        service.record_forensic_feedback(
            session_id=session_id,
            target_kind="pattern_match",
            target_ref="pattern_match:session-1:0",
            category="failure_family",
            outcome="different_family",
            reviewer="demo",
        )


def test_export_validations_filters_private_records_and_keeps_provenance(db_session, tmp_path):
    session_id = _seed_session(db_session)
    service = ValidationService(db_session)

    service._record(
        session_id=session_id,
        target_type="risk_flag",
        target_ref="abc123:coverage_gap",
        verdict="accept",
        reviewer="demo",
        confidence=0.95,
        notes="Great match",
        metadata_json={
            "node_id": "abc123",
            "flag_name": "coverage_gap",
            "review_outcome": {"label": "useful_failure", "target_type": "risk_flag"},
        },
        shareable=True,
    )
    service.record_signature_validation(
        session_id=session_id,
        signature_hash="zzz999",
        verdict="accept",
        reviewer="demo",
        confidence=0.95,
        notes="Private",
        shareable=False,
    )

    out_path = tmp_path / "export.jsonl"
    count = service.export_training_dataset_jsonl(out_path)

    assert count == 1
    lines = out_path.read_text().strip().splitlines()
    payload = json.loads(lines[0])
    assert payload["review_outcome"]["label"] == "useful_failure"
    assert payload["session_provenance"]["source_session_id"] == "dogfood-session-123"
    assert payload["session_provenance"]["source_path"] == "fixtures/dogfood/session.jsonl"
    assert payload["reviewer"] == "demo"


def test_record_validation_accepts_null_metadata_json(db_session):
    session_id = _seed_session(db_session)
    service = ValidationService(db_session)

    row = service._record(
        session_id=session_id,
        target_type="inflection",
        target_ref=str(uuid.uuid4()),
        verdict="accept",
        reviewer="demo",
        confidence=None,
        notes=None,
        metadata_json=None,
        shareable=False,
    )

    assert row.metadata_json is None


def test_record_validation_rejects_non_object_review_outcome(db_session):
    session_id = _seed_session(db_session)
    service = ValidationService(db_session)

    with pytest.raises(ValueError, match="review_outcome metadata must be an object"):
        service._record(
            session_id=session_id,
            target_type="inflection",
            target_ref=str(uuid.uuid4()),
            verdict="accept",
            reviewer="demo",
            confidence=None,
            notes=None,
            metadata_json={"review_outcome": "useful_failure"},
            shareable=False,
        )


def test_record_validation_rejects_contradictory_review_outcome_verdict(db_session):
    session_id = _seed_session(db_session)
    service = ValidationService(db_session)

    with pytest.raises(ValueError, match="requires verdict 'accept'"):
        service._record(
            session_id=session_id,
            target_type="risk_flag",
            target_ref=f"{uuid.uuid4()}:coverage_gap",
            verdict="reject",
            reviewer="demo",
            confidence=None,
            notes=None,
            metadata_json={
                "review_outcome": {"label": "useful_failure", "target_type": "risk_flag"},
            },
            shareable=False,
        )
