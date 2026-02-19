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
    CanonicalEvent, EventType, Session as DomainSession, SessionStatus,
)
from driftshield.core.analysis.session import analyze_session
from driftshield.db.models import Base
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
