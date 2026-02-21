import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from driftshield.core.models import (
    CanonicalEvent, EventType, RiskClassification,
    Session as DomainSession, SessionStatus,
)
from driftshield.core.analysis.session import analyze_session
from driftshield.db.models import (
    Base,
    DecisionNodeModel,
    RecurrenceSignatureModel,
    SessionModel,
    SessionSignatureModel,
)
from driftshield.db.persistence import PersistenceService


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture
def sample_analysis_result():
    """Create a minimal AnalysisResult from two events."""
    session_id = uuid.uuid4()
    event1 = CanonicalEvent(
        id=uuid.uuid4(),
        session_id=str(session_id),
        timestamp=datetime.now(timezone.utc),
        event_type=EventType.TOOL_CALL,
        agent_id="test-agent",
        action="read_file",
        inputs={"path": "/test"},
        outputs={"content": "data"},
    )
    event2 = CanonicalEvent(
        id=uuid.uuid4(),
        session_id=str(session_id),
        timestamp=datetime.now(timezone.utc),
        event_type=EventType.OUTPUT,
        agent_id="test-agent",
        action="respond",
        parent_event_id=event1.id,
    )
    domain_session = DomainSession(
        id=session_id,
        agent_id="test-agent",
        started_at=datetime.now(timezone.utc),
        status=SessionStatus.COMPLETED,
    )
    result = analyze_session([event1, event2])
    return result, domain_session


def test_save_analysis_result(db_session, sample_analysis_result):
    result, domain_session = sample_analysis_result
    service = PersistenceService(db_session)
    service.save(domain_session, result)
    db_session.commit()

    sessions = db_session.query(SessionModel).all()
    assert len(sessions) == 1
    assert sessions[0].agent_id == "test-agent"

    nodes = db_session.query(DecisionNodeModel).all()
    assert len(nodes) == 2
    assert nodes[0].session_id == domain_session.id


def test_load_session(db_session, sample_analysis_result):
    result, domain_session = sample_analysis_result
    service = PersistenceService(db_session)
    service.save(domain_session, result)
    db_session.commit()

    loaded = service.load_session(domain_session.id)
    assert loaded is not None
    assert loaded.id == domain_session.id
    assert loaded.agent_id == "test-agent"


def test_load_graph(db_session, sample_analysis_result):
    result, domain_session = sample_analysis_result
    service = PersistenceService(db_session)
    service.save(domain_session, result)
    db_session.commit()

    graph = service.load_graph(domain_session.id)
    assert graph is not None
    assert len(graph.nodes) == 2


def test_load_nonexistent_session(db_session):
    service = PersistenceService(db_session)
    loaded = service.load_session(uuid.uuid4())
    assert loaded is None


def test_list_sessions(db_session, sample_analysis_result):
    result, domain_session = sample_analysis_result
    service = PersistenceService(db_session)
    service.save(domain_session, result)
    db_session.commit()

    sessions, total = service.list_sessions(page=1, per_page=20)
    assert total == 1
    assert len(sessions) == 1
    assert sessions[0].id == domain_session.id


def test_list_sessions_pagination(db_session):
    service = PersistenceService(db_session)
    now = datetime.now(timezone.utc)
    for i in range(5):
        s = SessionModel(
            id=uuid.uuid4(), started_at=now, status="completed", agent_id=f"agent-{i}"
        )
        db_session.add(s)
    db_session.commit()

    sessions, total = service.list_sessions(page=1, per_page=2)
    assert total == 5
    assert len(sessions) == 2

    sessions, total = service.list_sessions(page=3, per_page=2)
    assert total == 5
    assert len(sessions) == 1


def test_save_persists_recurrence_signature_mapping(db_session):
    session_id = uuid.uuid4()
    event = CanonicalEvent(
        id=uuid.uuid4(),
        session_id=str(session_id),
        timestamp=datetime.now(timezone.utc),
        event_type=EventType.TOOL_CALL,
        agent_id="test-agent",
        action="review_indemnity",
        risk_classification=RiskClassification(coverage_gap=True),
    )
    session = DomainSession(
        id=session_id,
        agent_id="test-agent",
        started_at=datetime.now(timezone.utc),
        status=SessionStatus.COMPLETED,
    )
    result = analyze_session([event], historical_recurrence_counts={})

    service = PersistenceService(db_session)
    service.save(session, result)
    db_session.commit()

    signatures = db_session.query(RecurrenceSignatureModel).all()
    mappings = db_session.query(SessionSignatureModel).all()

    assert len(signatures) == 1
    assert signatures[0].signature_hash == result.recurrence.signature_hash
    assert signatures[0].occurrence_count == 1
    assert len(mappings) == 1
    assert mappings[0].session_id == session_id
