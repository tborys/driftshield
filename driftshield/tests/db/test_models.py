import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from driftshield.db.models import Base, SessionModel, DecisionNodeModel


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
