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
    assert connector["watch_status"] == "disabled"

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
    assert payload["watch_status"] == "idle"
    _assert_has_offset(payload["last_seen_activity_at"])


def test_connectors_cli_discovers_openclaw_agents(tmp_path, monkeypatch):
    project_dir = tmp_path / "repo"
    project_dir.mkdir()
    _write_openclaw_session(tmp_path, "main", session_id="main-1")
    _write_openclaw_session(tmp_path, "engineering", session_id="eng-1")

    db_path = tmp_path / "connectors.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("OPENCLAW_HOME", str(tmp_path / ".openclaw"))

    discovered = runner.invoke(
        app,
        ["connectors", "discover", "--project-dir", str(project_dir), "--json"],
    )
    assert discovered.exit_code == 0

    items = json.loads(discovered.stdout)
    source_types = {item["source_type"] for item in items}
    assert "openclaw_main" in source_types
    assert "openclaw_engineering" in source_types


def test_connectors_cli_watch_pause_and_resume_flow(tmp_path, monkeypatch):
    project_dir = tmp_path / "repo"
    project_dir.mkdir()
    _write_claude_session(tmp_path, project_dir, session_id="watch-cli")

    db_path = tmp_path / "connectors.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("CLAUDE_HOME", str(tmp_path / ".claude"))

    discovered = runner.invoke(
        app,
        ["connectors", "discover", "--project-dir", str(project_dir), "--json"],
    )
    connector = json.loads(discovered.stdout)[0]

    approved = runner.invoke(
        app,
        ["connectors", "approve", connector["id"], "--always"],
    )
    assert approved.exit_code == 0

    watched = runner.invoke(
        app,
        ["connectors", "watch", "--once", "--json"],
    )
    assert watched.exit_code == 0

    status = runner.invoke(
        app,
        ["connectors", "status", connector["id"], "--json"],
    )
    payload = json.loads(status.stdout)
    assert payload["watch_status"] == "idle"
    assert payload["last_ingested_at"] is not None
    _assert_has_offset(payload["last_ingested_at"])
    first_last_ingested_at = payload["last_ingested_at"]

    paused = runner.invoke(
        app,
        ["connectors", "pause", connector["id"]],
    )
    assert paused.exit_code == 0

    _append_claude_text_event(tmp_path, project_dir, "watch-cli", "resume should pick this up")
    paused_watch = runner.invoke(
        app,
        ["connectors", "watch", "--once", "--json"],
    )
    assert paused_watch.exit_code == 0

    paused_status = runner.invoke(
        app,
        ["connectors", "status", connector["id"], "--json"],
    )
    paused_payload = json.loads(paused_status.stdout)
    assert paused_payload["status"] == "paused"
    assert paused_payload["watch_status"] == "paused"
    assert paused_payload["last_ingested_at"] == first_last_ingested_at

    resumed = runner.invoke(
        app,
        ["connectors", "resume", connector["id"]],
    )
    assert resumed.exit_code == 0

    resumed_watch = runner.invoke(
        app,
        ["connectors", "watch", "--once", "--json"],
    )
    assert resumed_watch.exit_code == 0

    resumed_status = runner.invoke(
        app,
        ["connectors", "status", connector["id"], "--json"],
    )
    resumed_payload = json.loads(resumed_status.stdout)
    assert resumed_payload["status"] == "ready"
    assert resumed_payload["watch_status"] == "idle"
    assert resumed_payload["last_ingested_at"] is not None
    assert resumed_payload["last_ingested_at"] != first_last_ingested_at
