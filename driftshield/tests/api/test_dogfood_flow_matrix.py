import json
import os
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session as DBSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from driftshield.api.app import create_app
from driftshield.cli.discovery import path_to_project_key
from driftshield.connectors.watcher import ConnectorWatchService
from driftshield.db.models import Base, ConnectorModel, ConnectorSessionStateModel, DecisionNodeModel, SessionModel


@pytest.fixture
def db_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def db_session(db_engine):
    with DBSession(db_engine) as session:
        yield session


@pytest.fixture
def session_factory(db_engine):
    return sessionmaker(bind=db_engine, expire_on_commit=False)


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


def _session_path(base_dir: Path, project_dir: Path, session_id: str) -> Path:
    project_key = path_to_project_key(project_dir)
    sessions_dir = base_dir / ".claude" / "projects" / project_key
    sessions_dir.mkdir(parents=True, exist_ok=True)
    return sessions_dir / f"{session_id}.jsonl"


def _write_session_entry(base_dir: Path, project_dir: Path, session_id: str, entry: dict[str, object]) -> None:
    session_path = _session_path(base_dir, project_dir, session_id)
    with session_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry) + "\n")
    os.utime(session_path, None)


def _assistant_tool_use(session_id: str, tool_use_id: str, timestamp: str) -> dict[str, object]:
    return {
        "sessionId": session_id,
        "type": "assistant",
        "timestamp": timestamp,
        "message": {
            "model": "claude-sonnet",
            "content": [
                {
                    "type": "tool_use",
                    "id": tool_use_id,
                    "name": "review_sections",
                    "input": {"sections": ["intro", "body", "summary"]},
                }
            ],
        },
    }


def _user_tool_result(session_id: str, tool_use_id: str, timestamp: str) -> dict[str, object]:
    return {
        "sessionId": session_id,
        "type": "user",
        "timestamp": timestamp,
        "message": {
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": {"reviewed_sections": ["intro", "body"]},
                }
            ]
        },
    }


def _assistant_text(session_id: str, text: str, timestamp: str) -> dict[str, object]:
    return {
        "sessionId": session_id,
        "type": "assistant",
        "timestamp": timestamp,
        "message": {
            "model": "claude-sonnet",
            "content": [{"type": "text", "text": text}],
        },
    }


def test_dogfood_flow_matrix_smoke(client, auth_headers, session_factory, tmp_path, monkeypatch):
    project_dir = tmp_path / "repo"
    project_dir.mkdir()
    monkeypatch.setenv("CLAUDE_HOME", str(tmp_path / ".claude"))

    session_id = "dogfood-flow-1"
    _write_session_entry(
        tmp_path,
        project_dir,
        session_id,
        _assistant_tool_use(session_id, "tool-1", "2026-03-20T12:00:00+00:00"),
    )
    _write_session_entry(
        tmp_path,
        project_dir,
        session_id,
        _user_tool_result(session_id, "tool-1", "2026-03-20T12:00:01+00:00"),
    )

    discover = client.post(
        "/api/connectors/discover",
        headers=auth_headers,
        json={"project_dir": str(project_dir)},
    )
    assert discover.status_code == 200
    connector = discover.json()["items"][0]
    connector_id = connector["id"]
    assert connector["consent_state"] == "pending"
    assert connector["status"] == "proposed"
    assert connector["watch_status"] == "disabled"

    denied = client.post(f"/api/connectors/{connector_id}/deny", headers=auth_headers)
    assert denied.status_code == 200
    assert denied.json()["consent_state"] == "denied"
    assert denied.json()["status"] == "denied"

    blocked = client.post(f"/api/connectors/{connector_id}/rescan", headers=auth_headers)
    assert blocked.status_code == 409

    approved = client.post(
        f"/api/connectors/{connector_id}/approve",
        headers=auth_headers,
        json={"mode": "always"},
    )
    assert approved.status_code == 200
    assert approved.json()["consent_state"] == "approved_always"
    assert approved.json()["watch_status"] == "idle"

    rescanned = client.post(f"/api/connectors/{connector_id}/rescan", headers=auth_headers)
    assert rescanned.status_code == 200
    assert rescanned.json()["session_count"] == 1
    assert rescanned.json()["newest_session_id"] == session_id

    watcher = ConnectorWatchService(session_factory)
    watcher.run_once()

    connector_after_watch = client.get(f"/api/connectors/{connector_id}", headers=auth_headers)
    assert connector_after_watch.status_code == 200
    connector_payload = connector_after_watch.json()
    assert connector_payload["watch_status"] == "idle"
    assert connector_payload["last_ingested_at"] is not None
    assert connector_payload["metadata"]["tracked_session_count"] == 1
    assert connector_payload["metadata"]["ingested_session_count"] == 1

    with session_factory() as db:
        first_session_id = db.query(SessionModel).one().id
        first_session_count = db.query(SessionModel).count()
        first_node_count = db.query(DecisionNodeModel).count()
        first_state_count = db.query(ConnectorSessionStateModel).count()
        first_connector = db.get(ConnectorModel, UUID(connector_id))
        assert first_connector is not None
        first_last_ingested_at = first_connector.last_ingested_at
        assert first_last_ingested_at is not None

    sessions = client.get("/api/sessions?flagged_only=true", headers=auth_headers)
    assert sessions.status_code == 200
    items = sessions.json()["items"]
    assert len(items) == 1
    flagged_session_id = items[0]["id"]

    detail = client.get(f"/api/sessions/{flagged_session_id}", headers=auth_headers)
    assert detail.status_code == 200
    assert detail.json()["risk_summary"]["coverage_gap"] == 1

    graph = client.get(f"/api/sessions/{flagged_session_id}/graph", headers=auth_headers)
    assert graph.status_code == 200
    node = graph.json()["nodes"][0]
    assert node["risk_flags"] == ["coverage_gap"]

    review_payload = {
        "target_type": "risk_flag",
        "target_ref": f"{node['id']}:coverage_gap",
        "verdict": "accept",
        "reviewer": "demo",
        "confidence": 0.91,
        "notes": "Captured from dogfood smoke flow.",
        "metadata_json": {
            "node_id": node["id"],
            "flag_name": "coverage_gap",
            "review_outcome": {"label": "useful_failure", "target_type": "risk_flag"},
        },
        "shareable": True,
    }
    created_review = client.post(
        f"/api/sessions/{flagged_session_id}/validations",
        headers=auth_headers,
        json=review_payload,
    )
    assert created_review.status_code == 200
    assert created_review.json()["metadata_json"]["review_outcome"]["label"] == "useful_failure"

    listed_reviews = client.get(
        f"/api/sessions/{flagged_session_id}/validations",
        headers=auth_headers,
    )
    assert listed_reviews.status_code == 200
    assert len(listed_reviews.json()) == 1
    assert listed_reviews.json()[0]["reviewer"] == "demo"

    paused = client.post(f"/api/connectors/{connector_id}/pause", headers=auth_headers)
    assert paused.status_code == 200
    assert paused.json()["watch_status"] == "paused"

    _write_session_entry(
        tmp_path,
        project_dir,
        session_id,
        _assistant_text(session_id, "This append should wait until resume.", "2026-03-20T12:00:02+00:00"),
    )
    watcher.run_once()

    paused_status = client.get(f"/api/connectors/{connector_id}", headers=auth_headers)
    assert paused_status.status_code == 200
    assert paused_status.json()["status"] == "paused"
    assert paused_status.json()["watch_status"] == "paused"

    with session_factory() as db:
        paused_connector = db.get(ConnectorModel, UUID(connector_id))
        assert paused_connector is not None
        assert db.query(SessionModel).count() == first_session_count
        assert db.query(DecisionNodeModel).count() == first_node_count
        assert db.query(ConnectorSessionStateModel).count() == first_state_count
        assert db.query(SessionModel).one().id == first_session_id
        assert paused_connector.last_ingested_at == first_last_ingested_at

    resumed = client.post(f"/api/connectors/{connector_id}/resume", headers=auth_headers)
    assert resumed.status_code == 200
    watcher.run_once()

    resumed_status = client.get(f"/api/connectors/{connector_id}", headers=auth_headers)
    assert resumed_status.status_code == 200
    assert resumed_status.json()["status"] == "ready"
    assert resumed_status.json()["watch_status"] == "idle"

    with session_factory() as db:
        resumed_connector = db.get(ConnectorModel, UUID(connector_id))
        sessions_after_resume = db.query(SessionModel).all()
        nodes_after_resume = db.query(DecisionNodeModel).all()
        states_after_resume = db.query(ConnectorSessionStateModel).all()

        assert resumed_connector is not None
        assert len(sessions_after_resume) == first_session_count
        assert sessions_after_resume[0].id == first_session_id
        assert len(nodes_after_resume) == first_node_count + 1
        assert len(states_after_resume) == first_state_count
        assert resumed_connector.last_ingested_at is not None
        assert resumed_connector.last_ingested_at > first_last_ingested_at

    disconnected = client.post(f"/api/connectors/{connector_id}/disconnect", headers=auth_headers)
    assert disconnected.status_code == 200
    assert disconnected.json()["status"] == "disconnected"
    assert disconnected.json()["consent_state"] == "pending"

    reapproved = client.post(
        f"/api/connectors/{connector_id}/approve",
        headers=auth_headers,
        json={"mode": "always"},
    )
    assert reapproved.status_code == 200
    assert reapproved.json()["status"] == "ready"
    assert reapproved.json()["consent_state"] == "approved_always"
