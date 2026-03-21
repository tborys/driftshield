import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from driftshield.cli.discovery import path_to_project_key
from driftshield.connectors.watcher import ConnectorWatchService
from driftshield.db.connector_service import ConnectorService
from driftshield.db.models import (
    Base,
    ConnectorModel,
    ConnectorSessionStateModel,
    DecisionNodeModel,
    SessionModel,
)


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _session_path(base_dir: Path, project_dir: Path, session_id: str) -> Path:
    project_key = path_to_project_key(project_dir)
    sessions_dir = base_dir / ".claude" / "projects" / project_key
    sessions_dir.mkdir(parents=True, exist_ok=True)
    return sessions_dir / f"{session_id}.jsonl"


def _append_entries(
    base_dir: Path,
    project_dir: Path,
    session_id: str,
    entries: list[dict[str, object]],
) -> Path:
    session_path = _session_path(base_dir, project_dir, session_id)
    with session_path.open("a", encoding="utf-8") as handle:
        for entry in entries:
            handle.write(json.dumps(entry) + "\n")
    os.utime(session_path, None)
    return session_path


def _append_partial_line(base_dir: Path, project_dir: Path, session_id: str, raw: str) -> Path:
    session_path = _session_path(base_dir, project_dir, session_id)
    with session_path.open("a", encoding="utf-8") as handle:
        handle.write(raw)
    os.utime(session_path, None)
    return session_path


def _assistant_tool_use(session_id: str, tool_use_id: str, ts: datetime) -> dict[str, object]:
    return {
        "sessionId": session_id,
        "type": "assistant",
        "timestamp": ts.isoformat(),
        "message": {
            "model": "claude-sonnet",
            "content": [
                {
                    "type": "tool_use",
                    "id": tool_use_id,
                    "name": "Read",
                    "input": {"file_path": "/tmp/example.txt"},
                }
            ],
        },
    }


def _user_tool_result(session_id: str, tool_use_id: str, ts: datetime) -> dict[str, object]:
    return {
        "sessionId": session_id,
        "type": "user",
        "timestamp": ts.isoformat(),
        "message": {
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": "example file contents",
                }
            ]
        },
    }


def _assistant_text(session_id: str, text: str, ts: datetime) -> dict[str, object]:
    return {
        "sessionId": session_id,
        "type": "assistant",
        "timestamp": ts.isoformat(),
        "message": {
            "model": "claude-sonnet",
            "content": [{"type": "text", "text": text}],
        },
    }


def _create_ready_connector(
    *,
    session_factory,
    tmp_path: Path,
    project_dir: Path,
):
    with session_factory() as db:
        service = ConnectorService(db)
        connector = service.refresh_candidates(
            project_dir=project_dir,
            claude_home=tmp_path / ".claude",
        )[0]
        connector = service.approve_connector(connector.id, mode="always")
        db.commit()
        return connector.id


def test_watcher_incrementally_updates_existing_session_without_duplicates(tmp_path, session_factory):
    project_dir = tmp_path / "repo"
    project_dir.mkdir()
    connector_id = _create_ready_connector(
        session_factory=session_factory,
        tmp_path=tmp_path,
        project_dir=project_dir,
    )
    start = datetime(2026, 3, 20, 10, 0, tzinfo=timezone.utc)

    _append_entries(
        tmp_path,
        project_dir,
        "watch-1",
        [
            _assistant_tool_use("watch-1", "tool-1", start),
            _user_tool_result("watch-1", "tool-1", start + timedelta(seconds=1)),
        ],
    )

    watcher = ConnectorWatchService(session_factory)
    watcher.run_once()

    with session_factory() as db:
        connector = db.get(ConnectorModel, connector_id)
        sessions = db.query(SessionModel).all()
        nodes = db.query(DecisionNodeModel).all()
        states = db.query(ConnectorSessionStateModel).all()

        assert len(sessions) == 1
        assert len(nodes) == 1
        assert len(states) == 1
        assert states[0].session_model_id == sessions[0].id
        assert connector is not None
        assert connector.watch_status == "idle"
        assert connector.last_scanned_at is not None
        assert connector.last_ingested_at is not None
        assert connector.metadata_json["tracked_session_count"] == 1
        assert connector.metadata_json["ingested_session_count"] == 1

        first_session_id = sessions[0].id
        first_hash = sessions[0].transcript_hash
        first_ingested_at = connector.last_ingested_at

    watcher.run_once()

    with session_factory() as db:
        sessions = db.query(SessionModel).all()
        nodes = db.query(DecisionNodeModel).all()
        connector = ConnectorService(db).get_connector(connector_id)

        assert len(sessions) == 1
        assert len(nodes) == 1
        assert sessions[0].id == first_session_id
        assert sessions[0].transcript_hash == first_hash
        assert connector is not None
        assert connector.last_ingested_at == first_ingested_at

    _append_entries(
        tmp_path,
        project_dir,
        "watch-1",
        [
            _assistant_text("watch-1", "Found the next problem in the file.", start + timedelta(seconds=2)),
        ],
    )

    watcher.run_once()

    with session_factory() as db:
        connector = ConnectorService(db).get_connector(connector_id)
        sessions = db.query(SessionModel).all()
        nodes = db.query(DecisionNodeModel).order_by(DecisionNodeModel.sequence_num).all()
        states = db.query(ConnectorSessionStateModel).all()

        assert len(sessions) == 1
        assert len(nodes) == 2
        assert len(states) == 1
        assert sessions[0].id == first_session_id
        assert sessions[0].transcript_hash != first_hash
        assert connector is not None
        assert connector.last_ingested_at is not None
        assert connector.last_ingested_at > first_ingested_at
        assert connector.last_seen_activity_at is not None
        assert connector.metadata_json["tracked_session_count"] == 1
        assert connector.metadata_json["ingested_session_count"] == 1


def test_watcher_respects_pause_resume_and_restart_recovery(tmp_path, session_factory):
    project_dir = tmp_path / "repo"
    project_dir.mkdir()
    connector_id = _create_ready_connector(
        session_factory=session_factory,
        tmp_path=tmp_path,
        project_dir=project_dir,
    )
    start = datetime(2026, 3, 20, 11, 0, tzinfo=timezone.utc)

    _append_entries(
        tmp_path,
        project_dir,
        "watch-2",
        [
            _assistant_tool_use("watch-2", "tool-1", start),
            _user_tool_result("watch-2", "tool-1", start + timedelta(seconds=1)),
        ],
    )

    ConnectorWatchService(session_factory).run_once()

    with session_factory() as db:
        service = ConnectorService(db)
        session_id = db.query(SessionModel).one().id
        service.pause_connector(connector_id)
        db.commit()

    _append_entries(
        tmp_path,
        project_dir,
        "watch-2",
        [
            _assistant_text("watch-2", "This append should wait until resume.", start + timedelta(seconds=2)),
        ],
    )

    ConnectorWatchService(session_factory).run_once()

    with session_factory() as db:
        connector = ConnectorService(db).get_connector(connector_id)
        assert connector is not None
        assert connector.status == "paused"
        assert connector.watch_status == "paused"
        assert db.query(SessionModel).count() == 1
        assert db.query(DecisionNodeModel).count() == 1

        resumed = ConnectorService(db).resume_connector(connector_id)
        db.commit()
        assert resumed.status == "ready"

    ConnectorWatchService(session_factory).run_once()

    with session_factory() as db:
        connector = ConnectorService(db).get_connector(connector_id)
        sessions = db.query(SessionModel).all()
        nodes = db.query(DecisionNodeModel).all()
        states = db.query(ConnectorSessionStateModel).all()

        assert connector is not None
        assert connector.status == "ready"
        assert connector.watch_status == "idle"
        assert len(sessions) == 1
        assert sessions[0].id == session_id
        assert len(nodes) == 2
        assert len(states) == 1
        assert states[0].session_model_id == session_id


def test_watcher_handles_partial_reads_without_duplicate_nodes(tmp_path, session_factory):
    project_dir = tmp_path / "repo"
    project_dir.mkdir()
    _create_ready_connector(
        session_factory=session_factory,
        tmp_path=tmp_path,
        project_dir=project_dir,
    )
    start = datetime(2026, 3, 20, 12, 0, tzinfo=timezone.utc)

    _append_entries(
        tmp_path,
        project_dir,
        "watch-3",
        [
            _assistant_tool_use("watch-3", "tool-1", start),
            _user_tool_result("watch-3", "tool-1", start + timedelta(seconds=1)),
        ],
    )

    watcher = ConnectorWatchService(session_factory)
    watcher.run_once()

    with session_factory() as db:
        first_session_id = db.query(SessionModel).one().id
        first_node_count = db.query(DecisionNodeModel).count()

    _append_partial_line(
        tmp_path,
        project_dir,
        "watch-3",
        partial_line := json.dumps(
            _assistant_text(
                "watch-3",
                "This line is only partially written",
                start + timedelta(seconds=2),
            )
        )[:-8],
    )

    watcher.run_once()

    with session_factory() as db:
        assert db.query(SessionModel).count() == 1
        assert db.query(DecisionNodeModel).count() == first_node_count
        assert db.query(SessionModel).one().id == first_session_id

    _append_partial_line(
        tmp_path,
        project_dir,
        "watch-3",
        json.dumps(
            _assistant_text("watch-3", "This line is only partially written", start + timedelta(seconds=2))
        )[len(partial_line):]
        + "\n",
    )

    watcher.run_once()

    with session_factory() as db:
        assert db.query(SessionModel).count() == 1
        assert db.query(SessionModel).one().id == first_session_id
        assert db.query(DecisionNodeModel).count() == first_node_count + 1
