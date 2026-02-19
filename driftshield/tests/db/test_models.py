import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from driftshield.db.models import Base, SessionModel


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
