import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session as DBSession
from sqlalchemy.pool import StaticPool

from driftshield.api.app import create_app
from driftshield.core.analysis.session import analyze_session
from driftshield.core.models import Session as DomainSession, SessionStatus
from driftshield.db.models import Base, SessionModel, DecisionNodeModel
from driftshield.db.persistence import PersistenceService
from tests.fixtures.lineage import branching_lineage_events


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
def seeded_graph(db_session):
    session_id = uuid.uuid4()
    s = SessionModel(
        id=session_id, agent_id="test", started_at=datetime.now(timezone.utc), status="completed"
    )
    parent_id = uuid.uuid4()
    child_id = uuid.uuid4()
    parent = DecisionNodeModel(
        id=parent_id, session_id=session_id, sequence_num=1,
        event_type="TOOL_CALL", action="start", coverage_gap=True, is_inflection_node=True,
    )
    child = DecisionNodeModel(
        id=child_id, session_id=session_id, parent_node_id=parent_id, sequence_num=2,
        event_type="OUTPUT", action="respond",
    )
    db_session.add_all([s, parent, child])
    db_session.commit()
    return session_id, parent_id, child_id


def test_get_graph(client, auth_headers, seeded_graph):
    session_id, parent_id, child_id = seeded_graph
    response = client.get(f"/api/sessions/{session_id}/graph", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["session_id"] == str(session_id)
    assert len(data["nodes"]) == 2
    assert len(data["edges"]) == 1
    assert data["edges"][0]["source"] == str(parent_id)
    assert data["edges"][0]["target"] == str(child_id)

    # Check inflection node is marked
    inflection_nodes = [n for n in data["nodes"] if n["is_inflection"]]
    assert len(inflection_nodes) == 1

    # Check risk flags are listed
    flagged_nodes = [n for n in data["nodes"] if len(n["risk_flags"]) > 0]
    assert len(flagged_nodes) == 1
    assert "coverage_gap" in flagged_nodes[0]["risk_flags"]


def test_get_graph_not_found(client, auth_headers):
    response = client.get(f"/api/sessions/{uuid.uuid4()}/graph", headers=auth_headers)
    assert response.status_code == 404


def test_get_graph_returns_branching_lineage_metadata(client, auth_headers, db_session):
    session_id = uuid.uuid4()
    events = branching_lineage_events(str(session_id))
    result = analyze_session(events)

    PersistenceService(db_session).save(
        DomainSession(
            id=session_id,
            agent_id="test-agent",
            started_at=datetime.now(timezone.utc),
            status=SessionStatus.COMPLETED,
        ),
        result,
    )
    db_session.commit()

    response = client.get(f"/api/sessions/{session_id}/graph", headers=auth_headers)

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["edges"]) == 4

    merge_node = next(node for node in payload["nodes"] if node["action"] == "synthesize_findings")
    assert merge_node["parent_node_id"] == str(events[1].id)
    assert merge_node["parent_node_ids"] == [str(events[1].id), str(events[2].id)]
    assert merge_node["evidence_refs"]

    merge_edges = [edge for edge in payload["edges"] if edge["target"] == str(events[-1].id)]
    assert len(merge_edges) == 2
    assert [edge["source"] for edge in merge_edges] == [str(events[1].id), str(events[2].id)]
    assert all(edge["relationship"] == "explicit_parent" for edge in merge_edges)
    assert all(edge["confidence"] == 1.0 for edge in merge_edges)
