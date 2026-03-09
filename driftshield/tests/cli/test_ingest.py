"""Tests for ingest command and Dealer hook wrapper."""

from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path

from typer.testing import CliRunner

from driftshield.cli.main import app
from driftshield.cli.discovery import path_to_project_key
from driftshield.cli.commands.ingest import _build_multipart_body


runner = CliRunner()
FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "transcripts"
REPO_ROOT = Path(__file__).resolve().parents[3]
HOOK_SCRIPT = REPO_ROOT / "scripts" / "dealer-hook.sh"


class DummyResponse:
    def __init__(self, status: int = 201, payload: dict | None = None):
        self.status = status
        self._payload = payload or {
            "session_id": "11111111-1111-1111-1111-111111111111",
            "total_events": 2,
            "flagged_events": 0,
            "has_inflection": False,
            "status": "created",
            "deduplicated": False,
        }

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self) -> "DummyResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


def _write_project_sessions(tmp_path: Path) -> tuple[Path, Path, Path]:
    project_dir = tmp_path / "repo"
    project_dir.mkdir()

    project_key = path_to_project_key(project_dir)
    sessions_dir = tmp_path / ".claude" / "projects" / project_key
    sessions_dir.mkdir(parents=True)

    fixture = FIXTURES_DIR / "sample_claude_code_session.jsonl"
    oldest = sessions_dir / "2026-03-01-old.jsonl"
    newest = sessions_dir / "2026-03-02-new.jsonl"
    oldest.write_text(fixture.read_text())
    newest.write_text(fixture.read_text())

    oldest.touch()
    newest.touch()
    os.utime(oldest, (1_700_000_000, 1_700_000_000))
    os.utime(newest, (1_800_000_000, 1_800_000_000))
    return project_dir, oldest, newest


def test_ingest_with_path_posts_selected_file(monkeypatch):
    captured: dict[str, object] = {}

    def fake_post_ingest(*, target_url: str, api_key: str, file_path: Path, parser: str):
        captured.update(
            {
                "target_url": target_url,
                "api_key": api_key,
                "file_path": file_path,
                "parser": parser,
            }
        )
        return DummyResponse()._payload

    monkeypatch.setenv("DRIFTSHIELD_API_URL", "http://localhost:8000")
    monkeypatch.setenv("DRIFTSHIELD_API_KEY", "test-key")
    monkeypatch.setattr("driftshield.cli.commands.ingest.post_ingest", fake_post_ingest)

    transcript = FIXTURES_DIR / "sample_claude_code_session.jsonl"
    result = runner.invoke(app, ["ingest", "--path", str(transcript)])

    assert result.exit_code == 0
    assert captured == {
        "target_url": "http://localhost:8000/api/ingest",
        "api_key": "test-key",
        "file_path": transcript,
        "parser": "claude_code",
    }
    assert "created" in result.output.lower()


def test_ingest_with_project_uses_most_recent_project_session(tmp_path, monkeypatch):
    project_dir, _oldest, newest = _write_project_sessions(tmp_path)

    captured: dict[str, object] = {}

    def fake_post_ingest(*, target_url: str, api_key: str, file_path: Path, parser: str):
        captured["file_path"] = file_path
        return DummyResponse()._payload

    monkeypatch.chdir(project_dir)
    monkeypatch.setenv("CLAUDE_HOME", str(tmp_path / ".claude"))
    monkeypatch.setenv("DRIFTSHIELD_API_URL", "http://localhost:8000")
    monkeypatch.setenv("DRIFTSHIELD_API_KEY", "test-key")
    monkeypatch.setattr("driftshield.cli.commands.ingest.post_ingest", fake_post_ingest)

    result = runner.invoke(app, ["ingest", "--project"])

    assert result.exit_code == 0
    assert captured["file_path"] == newest


def test_ingest_with_latest_uses_existing_discovery_logic(tmp_path, monkeypatch):
    project_dir, _oldest, newest = _write_project_sessions(tmp_path)

    captured: dict[str, object] = {}

    def fake_post_ingest(*, target_url: str, api_key: str, file_path: Path, parser: str):
        captured["file_path"] = file_path
        return DummyResponse()._payload

    monkeypatch.chdir(project_dir)
    monkeypatch.setenv("CLAUDE_HOME", str(tmp_path / ".claude"))
    monkeypatch.setenv("DRIFTSHIELD_API_URL", "http://localhost:8000")
    monkeypatch.setenv("DRIFTSHIELD_API_KEY", "test-key")
    monkeypatch.setattr("driftshield.cli.commands.ingest.post_ingest", fake_post_ingest)

    result = runner.invoke(app, ["ingest", "--latest"])

    assert result.exit_code == 0
    assert captured["file_path"] == newest


def test_ingest_surfaces_deduplicated_response(monkeypatch):
    deduped = {
        "session_id": "11111111-1111-1111-1111-111111111111",
        "total_events": 2,
        "flagged_events": 0,
        "has_inflection": False,
        "status": "deduped",
        "deduplicated": True,
    }

    def fake_post_ingest(*, target_url: str, api_key: str, file_path: Path, parser: str):
        return deduped

    monkeypatch.setenv("DRIFTSHIELD_API_URL", "http://localhost:8000")
    monkeypatch.setenv("DRIFTSHIELD_API_KEY", "test-key")
    monkeypatch.setattr("driftshield.cli.commands.ingest.post_ingest", fake_post_ingest)

    transcript = FIXTURES_DIR / "sample_claude_code_session.jsonl"
    result = runner.invoke(app, ["ingest", "--path", str(transcript)])

    assert result.exit_code == 0
    assert "deduped" in result.output.lower()
    assert "duplicate" in result.output.lower() or "already" in result.output.lower()


def test_build_multipart_body_uses_basename_for_uploaded_filename():
    transcript = FIXTURES_DIR / "sample_claude_code_session.jsonl"

    body = _build_multipart_body(
        boundary="test-boundary",
        file_path=transcript,
        parser="claude_code",
    )

    decoded = body.decode("utf-8", errors="ignore")
    assert 'filename="sample_claude_code_session.jsonl"' in decoded
    assert str(transcript) not in decoded


def test_dealer_hook_wrapper_targets_local_ingest(tmp_path):
    assert HOOK_SCRIPT.exists(), "dealer hook wrapper should exist"

    fake_driftshield = tmp_path / "driftshield"
    fake_driftshield.write_text(
        "#!/bin/sh\n"
        "printf '%s\n' \"$@\" > \"$HOOK_CAPTURE\"\n"
    )
    fake_driftshield.chmod(fake_driftshield.stat().st_mode | stat.S_IEXEC)

    capture = tmp_path / "hook-local.txt"
    transcript = FIXTURES_DIR / "sample_claude_code_session.jsonl"
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{tmp_path}:{env['PATH']}",
            "HOOK_CAPTURE": str(capture),
            "CLAUDE_TRANSCRIPT_PATH": str(transcript),
        }
    )

    result = subprocess.run([str(HOOK_SCRIPT), "local"], env=env, capture_output=True, text=True)

    assert result.returncode == 0, result.stderr
    assert capture.read_text().splitlines() == ["ingest", "--path", str(transcript)]


def test_dealer_hook_wrapper_targets_vps_ingest(tmp_path):
    assert HOOK_SCRIPT.exists(), "dealer hook wrapper should exist"

    fake_curl = tmp_path / "curl"
    fake_curl.write_text(
        "#!/bin/sh\n"
        "printf '%s\n' \"$@\" > \"$HOOK_CAPTURE\"\n"
    )
    fake_curl.chmod(fake_curl.stat().st_mode | stat.S_IEXEC)

    capture = tmp_path / "hook-vps.txt"
    transcript = FIXTURES_DIR / "sample_claude_code_session.jsonl"
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{tmp_path}:{env['PATH']}",
            "HOOK_CAPTURE": str(capture),
            "CLAUDE_TRANSCRIPT_PATH": str(transcript),
            "DRIFTSHIELD_API_URL": "https://driftshield.example",
            "DRIFTSHIELD_API_KEY": "test-key",
        }
    )

    result = subprocess.run([str(HOOK_SCRIPT), "vps"], env=env, capture_output=True, text=True)

    assert result.returncode == 0, result.stderr
    args = capture.read_text().splitlines()
    assert "-X" in args and "POST" in args
    assert "https://driftshield.example/api/ingest" in args
    assert any(part == "X-API-Key: test-key" for part in args)
    assert any(str(transcript) in part for part in args)
