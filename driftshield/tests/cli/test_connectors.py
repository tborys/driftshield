import json
import os
from pathlib import Path

from typer.testing import CliRunner

from driftshield.cli.discovery import path_to_project_key
from driftshield.cli.main import app


runner = CliRunner()


def _write_claude_session(base_dir: Path, project_dir: Path, session_id: str = "session-1") -> None:
    project_key = path_to_project_key(project_dir)
    sessions_dir = base_dir / ".claude" / "projects" / project_key
    sessions_dir.mkdir(parents=True, exist_ok=True)
    session_path = sessions_dir / f"{session_id}.jsonl"
    session_path.write_text(
        json.dumps({"sessionId": session_id, "type": "assistant"}) + "\n"
    )
    os.utime(session_path, (1_800_000_000, 1_800_000_000))


def _assert_has_offset(value: str) -> None:
    assert value.endswith("+00:00") or value.endswith("Z")


def test_connectors_cli_discovery_and_rescan_flow(tmp_path, monkeypatch):
    project_dir = tmp_path / "repo"
    project_dir.mkdir()
    _write_claude_session(tmp_path, project_dir, session_id="abc123")

    db_path = tmp_path / "connectors.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("CLAUDE_HOME", str(tmp_path / ".claude"))

    discovered = runner.invoke(
        app,
        ["connectors", "discover", "--project-dir", str(project_dir), "--json"],
    )
    assert discovered.exit_code == 0
    connector = json.loads(discovered.stdout)[0]

    blocked = runner.invoke(app, ["connectors", "rescan", connector["id"]])
    assert blocked.exit_code == 1
    assert "approval" in blocked.stdout.lower()

    approved = runner.invoke(
        app,
        ["connectors", "approve", connector["id"], "--always"],
    )
    assert approved.exit_code == 0

    rescanned = runner.invoke(
        app,
        ["connectors", "rescan", connector["id"], "--json"],
    )
    assert rescanned.exit_code == 0
    scan = json.loads(rescanned.stdout)
    assert scan["session_count"] == 1
    assert scan["newest_session_id"] == "abc123"
    _assert_has_offset(scan["newest_modified_at"])

    status = runner.invoke(
        app,
        ["connectors", "status", connector["id"], "--json"],
    )
    assert status.exit_code == 0
    payload = json.loads(status.stdout)
    assert payload["consent_state"] == "approved_always"
    assert payload["status"] == "ready"
    _assert_has_offset(payload["last_seen_activity_at"])
