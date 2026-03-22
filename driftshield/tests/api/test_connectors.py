import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session as DBSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from driftshield.api.app import create_app
from driftshield.cli.discovery import path_to_project_key
from driftshield.connectors.watcher import ConnectorWatchService
from driftshield.db.models import Base


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


def _write_claude_session(base_dir: Path, project_dir: Path, session_id: str = "session-1") -> None:
    project_key = path_to_project_key(project_dir)
    sessions_dir = base_dir / ".claude" / "projects" / project_key
    sessions_dir.mkdir(parents=True, exist_ok=True)
    session_path = sessions_dir / f"{session_id}.jsonl"
    session_path.write_text(
        json.dumps(
            {
                "sessionId": session_id,
                "type": "assistant",
                "timestamp": "2026-03-20T12:00:00+00:00",
                "message": {
                    "model": "claude-sonnet",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "tool_1",
                            "name": "Read",
                            "input": {"file_path": "/tmp/example.txt"},
                        }
                    ],
                },
            }
        )
        + "\n"
    )
    os.utime(session_path, (1_800_000_000, 1_800_000_000))


def _write_openclaw_session(base_dir: Path, agent_name: str, session_id: str = "session-1") -> None:
    sessions_dir = base_dir / ".openclaw" / "agents" / agent_name / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    session_path = sessions_dir / f"{session_id}.jsonl"
    session_path.write_text(json.dumps({"type": "session", "id": session_id}) + "\n")
    os.utime(session_path, (1_800_000_000, 1_800_000_000))


def _append_claude_text_event(base_dir: Path, project_dir: Path, session_id: str, text: str) -> None:
    project_key = path_to_project_key(project_dir)
    session_path = base_dir / ".claude" / "projects" / project_key / f"{session_id}.jsonl"
    with session_path.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "sessionId": session_id,
                    "type": "assistant",
                    "timestamp": "2026-03-20T12:00:00+00:00",
                    "message": {
                        "model": "claude-sonnet",
                        "content": [{"type": "text", "text": text}],
                    },
                }
            )
            + "\n"
        )
    os.utime(session_path, None)


def _assert_has_offset(value: str) -> None:
    assert value.endswith("+00:00") or value.endswith("Z")


def test_connector_discovery_approve_and_rescan_flow(client, auth_headers, tmp_path, monkeypatch):
    project_dir = tmp_path / "repo"
    project_dir.mkdir()
    _write_claude_session(tmp_path, project_dir, session_id="abc123")
    monkeypatch.setenv("CLAUDE_HOME", str(tmp_path / ".claude"))

    discover = client.post(
        "/api/connectors/discover",
        headers=auth_headers,
        json={"project_dir": str(project_dir)},
    )

    assert discover.status_code == 200
    connector = discover.json()["items"][0]
    assert connector["source_type"] == "claude_code"
    assert connector["consent_state"] == "pending"
    assert connector["status"] == "proposed"
    assert connector["watch_status"] == "disabled"
    assert connector["last_scanned_at"] is None

    blocked = client.post(
        f"/api/connectors/{connector['id']}/rescan",
        headers=auth_headers,
    )
    assert blocked.status_code == 409

    approved = client.post(
        f"/api/connectors/{connector['id']}/approve",
        headers=auth_headers,
        json={"mode": "always"},
    )
    assert approved.status_code == 200
    assert approved.json()["consent_state"] == "approved_always"
    assert approved.json()["watch_status"] == "idle"

    rescanned = client.post(
        f"/api/connectors/{connector['id']}/rescan",
        headers=auth_headers,
    )
    assert rescanned.status_code == 200
    assert rescanned.json()["session_count"] == 1
    assert rescanned.json()["newest_session_id"] == "abc123"
    _assert_has_offset(rescanned.json()["newest_modified_at"])

    status = client.get(
        f"/api/connectors/{connector['id']}",
        headers=auth_headers,
    )
    assert status.status_code == 200
    assert status.json()["status"] == "ready"
    assert status.json()["watch_status"] == "idle"
    assert status.json()["metadata"]["session_count"] == 1
    _assert_has_offset(status.json()["last_seen_activity_at"])


def test_connector_discovery_lists_openclaw_agents(client, auth_headers, tmp_path, monkeypatch):
    project_dir = tmp_path / "repo"
    project_dir.mkdir()
    _write_openclaw_session(tmp_path, "business", session_id="biz-1")
    monkeypatch.setenv("OPENCLAW_HOME", str(tmp_path / ".openclaw"))

    discover = client.post(
        "/api/connectors/discover",
        headers=auth_headers,
        json={"project_dir": str(project_dir)},
    )

    assert discover.status_code == 200
    items = discover.json()["items"]
    assert any(item["source_type"] == "openclaw_business" for item in items)
    assert any(item["parser_name"] == "openclaw" for item in items)


def test_connector_api_exposes_watch_status_and_resume_flow(
    client,
    auth_headers,
    tmp_path,
    monkeypatch,
    db_session,
):
    project_dir = tmp_path / "repo"
    project_dir.mkdir()
    _write_claude_session(tmp_path, project_dir, session_id="watch-api")
    monkeypatch.setenv("CLAUDE_HOME", str(tmp_path / ".claude"))

    discover = client.post(
        "/api/connectors/discover",
        headers=auth_headers,
        json={"project_dir": str(project_dir)},
    )
    connector = discover.json()["items"][0]

    approved = client.post(
        f"/api/connectors/{connector['id']}/approve",
        headers=auth_headers,
        json={"mode": "always"},
    )
    assert approved.status_code == 200

    session_factory = sessionmaker(bind=db_session.bind, expire_on_commit=False)
    ConnectorWatchService(session_factory).run_once()

    watched = client.get(
        f"/api/connectors/{connector['id']}",
        headers=auth_headers,
    )
    assert watched.status_code == 200
    payload = watched.json()
    assert payload["watch_status"] == "idle"
    assert payload["last_ingested_at"] is not None
    assert payload["metadata"]["tracked_session_count"] == 1
    assert payload["metadata"]["ingested_session_count"] == 1
    _assert_has_offset(payload["last_ingested_at"])

    paused = client.post(
        f"/api/connectors/{connector['id']}/pause",
        headers=auth_headers,
    )
    assert paused.status_code == 200
    assert paused.json()["status"] == "paused"
    assert paused.json()["watch_status"] == "paused"

    _append_claude_text_event(tmp_path, project_dir, "watch-api", "wait until resumed")
    ConnectorWatchService(session_factory).run_once()

    still_paused = client.get(
        f"/api/connectors/{connector['id']}",
        headers=auth_headers,
    )
    assert still_paused.status_code == 200
    assert still_paused.json()["status"] == "paused"
    assert still_paused.json()["watch_status"] == "paused"

    resumed = client.post(
        f"/api/connectors/{connector['id']}/resume",
        headers=auth_headers,
    )
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "ready"
    assert resumed.json()["watch_status"] == "idle"
