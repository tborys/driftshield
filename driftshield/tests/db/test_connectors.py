import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from driftshield.cli.discovery import discover_sessions_in_path, path_to_project_key
from driftshield.connectors.registry import CONNECTOR_ADAPTERS, DiscoveryContext
from driftshield.db.connector_service import ConnectorService
from driftshield.db.models import Base


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _write_claude_session(base_dir: Path, project_dir: Path, session_id: str = "session-1") -> Path:
    project_key = path_to_project_key(project_dir)
    sessions_dir = base_dir / ".claude" / "projects" / project_key
    sessions_dir.mkdir(parents=True, exist_ok=True)
    transcript = sessions_dir / f"{session_id}.jsonl"
    transcript.write_text(json.dumps({"sessionId": session_id, "type": "assistant"}) + "\n")
    return transcript


def test_refresh_candidates_persists_unscanned_connector(tmp_path, db_session):
    project_dir = tmp_path / "repo"
    project_dir.mkdir()

    service = ConnectorService(db_session)
    connectors = service.refresh_candidates(
        project_dir=project_dir,
        claude_home=tmp_path / ".claude",
        codex_home=tmp_path / ".codex",
    )

    source_types = {connector.source_type for connector in connectors}
    assert {"claude_code", "claude_desktop", "codex_cli", "codex_desktop"}.issubset(source_types)

    claude_code = next(connector for connector in connectors if connector.source_type == "claude_code")
    assert claude_code.root_path == str(
        tmp_path / ".claude" / "projects" / path_to_project_key(project_dir)
    )
    assert claude_code.consent_state == "pending"
    assert claude_code.status == "proposed"
    assert claude_code.last_scanned_at is None
    assert claude_code.metadata_json["path_exists"] is False


def test_rescan_requires_explicit_approval_and_consumes_approve_once(tmp_path, db_session):
    project_dir = tmp_path / "repo"
    project_dir.mkdir()
    _write_claude_session(tmp_path, project_dir, session_id="abc123")

    service = ConnectorService(db_session)
    connector = service.refresh_candidates(
        project_dir=project_dir,
        claude_home=tmp_path / ".claude",
    )[0]

    with pytest.raises(ValueError, match="approval"):
        service.rescan_connector(connector.id)

    service.approve_connector(connector.id, mode="once")
    scan = service.rescan_connector(connector.id)
    refreshed = service.get_connector(connector.id)

    assert scan.session_count == 1
    assert scan.newest_session_id == "abc123"
    assert refreshed is not None
    assert refreshed.last_scanned_at is not None
    assert refreshed.metadata_json["session_count"] == 1
    assert refreshed.consent_state == "pending"
    assert refreshed.status == "proposed"


def test_connector_supports_deny_pause_disconnect_and_reapprove(tmp_path, db_session):
    project_dir = tmp_path / "repo"
    project_dir.mkdir()

    service = ConnectorService(db_session)
    connector = service.refresh_candidates(
        project_dir=project_dir,
        claude_home=tmp_path / ".claude",
    )[0]

    denied = service.deny_connector(connector.id)
    assert denied.consent_state == "denied"
    assert denied.status == "denied"

    ready = service.approve_connector(connector.id, mode="always")
    assert ready.consent_state == "approved_always"
    assert ready.status == "ready"

    paused = service.pause_connector(connector.id)
    assert paused.status == "paused"
    assert paused.consent_state == "approved_always"

    disconnected = service.disconnect_connector(connector.id)
    assert disconnected.status == "disconnected"
    assert disconnected.consent_state == "pending"

    reapproved = service.approve_connector(connector.id, mode="always")
    assert reapproved.status == "ready"
    assert reapproved.consent_state == "approved_always"


def test_discover_sessions_in_path_can_limit_patterns(tmp_path):
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    (sessions_dir / "session.jsonl").write_text('{"sessionId": "abc"}\n')
    (sessions_dir / "not-a-session.json").write_text('{"foo": "bar"}')

    sessions = discover_sessions_in_path(sessions_dir, patterns=("*.jsonl",))

    assert [session.path.name for session in sessions] == ["session.jsonl"]


def test_fixed_path_connector_uses_explicit_non_dot_home_as_base_root(tmp_path):
    adapter = CONNECTOR_ADAPTERS["codex_desktop"]
    context = DiscoveryContext(project_dir=tmp_path / "repo", codex_home=tmp_path / "codex-data")

    candidate = adapter.build_candidate(context)

    assert candidate.root_path == tmp_path / "codex-data" / ".codex-desktop" / "sessions"
