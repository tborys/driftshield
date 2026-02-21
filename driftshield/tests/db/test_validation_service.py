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


def test_export_validations_filters_private_records(db_session, tmp_path):
    session_id = _seed_session(db_session)
    service = ValidationService(db_session)

    service.record_signature_validation(
        session_id=session_id,
        signature_hash="abc123",
        verdict="accept",
        reviewer="demo",
        confidence=0.95,
        notes="Great match",
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
    assert payload["signature_hash"] == "abc123"
    assert payload["reviewer"] == "demo"
