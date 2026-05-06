"""Tests for ingest command."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from driftshield.cli.main import app
from driftshield.cli.discovery import path_to_project_key
from driftshield.cli.commands.ingest import (
    SourceConnectorMetadata,
    SubmissionContext,
    _build_multipart_body,
    build_submission_context,
)


runner = CliRunner()
FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "transcripts"


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

    def fake_post_ingest(*, target_url: str, api_key: str, file_path: Path, parser: str, submission_context: SubmissionContext):
        captured.update(
            {
                "target_url": target_url,
                "api_key": api_key,
                "file_path": file_path,
                "parser": parser,
                "submission_context": submission_context,
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
        "submission_context": SubmissionContext(submission_tier="oss"),
    }
    assert "created" in result.output.lower()


def test_ingest_with_project_uses_most_recent_project_session(tmp_path, monkeypatch):
    project_dir, _oldest, newest = _write_project_sessions(tmp_path)

    captured: dict[str, object] = {}

    def fake_post_ingest(*, target_url: str, api_key: str, file_path: Path, parser: str, submission_context: SubmissionContext):
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

    def fake_post_ingest(*, target_url: str, api_key: str, file_path: Path, parser: str, submission_context: SubmissionContext):
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

    def fake_post_ingest(*, target_url: str, api_key: str, file_path: Path, parser: str, submission_context: SubmissionContext):
        return deduped

    monkeypatch.setenv("DRIFTSHIELD_API_URL", "http://localhost:8000")
    monkeypatch.setenv("DRIFTSHIELD_API_KEY", "test-key")
    monkeypatch.setattr("driftshield.cli.commands.ingest.post_ingest", fake_post_ingest)

    transcript = FIXTURES_DIR / "sample_claude_code_session.jsonl"
    result = runner.invoke(app, ["ingest", "--path", str(transcript)])

    assert result.exit_code == 0
    assert "deduped" in result.output.lower()
    assert "duplicate" in result.output.lower() or "already" in result.output.lower()


def test_ingest_with_explicit_crewai_parser(monkeypatch):
    captured: dict[str, object] = {}

    def fake_post_ingest(*, target_url: str, api_key: str, file_path: Path, parser: str, submission_context: SubmissionContext):
        captured["parser"] = parser
        return DummyResponse()._payload

    monkeypatch.setenv("DRIFTSHIELD_API_URL", "http://localhost:8000")
    monkeypatch.setenv("DRIFTSHIELD_API_KEY", "test-key")
    monkeypatch.setattr("driftshield.cli.commands.ingest.post_ingest", fake_post_ingest)

    transcript = FIXTURES_DIR / "sample_crewai_session.json"
    result = runner.invoke(app, ["ingest", "--path", str(transcript), "--parser", "crewai"])

    assert result.exit_code == 0
    assert captured["parser"] == "crewai"


def test_build_multipart_body_uses_basename_for_uploaded_filename():
    transcript = FIXTURES_DIR / "sample_claude_code_session.jsonl"

    body = _build_multipart_body(
        boundary="test-boundary",
        file_path=transcript,
        parser="claude_code",
        submission_context=SubmissionContext(submission_tier="oss"),
    )

    decoded = body.decode("utf-8", errors="ignore")
    assert 'filename="sample_claude_code_session.jsonl"' in decoded
    assert str(transcript) not in decoded


def test_build_multipart_body_includes_teams_context_and_source_connector_metadata():
    transcript = FIXTURES_DIR / "sample_claude_code_session.jsonl"

    body = _build_multipart_body(
        boundary="test-boundary",
        file_path=transcript,
        parser="claude_code",
        submission_context=SubmissionContext(
            submission_tier="teams",
            tenant_id="tenant-acme",
            workspace_id="workspace-core",
            workflow_reference="wf-triage",
            project_reference="proj-risk",
            source_connector=SourceConnectorMetadata(
                connector_id="connector-1",
                source_type="claude_code",
                display_name="Core Claude",
                parser_name="claude_code",
            ),
        ),
    )

    decoded = body.decode("utf-8", errors="ignore")
    assert 'name="submission_tier"' in decoded
    assert "teams" in decoded
    assert 'name="tenant_id"' in decoded
    assert "tenant-acme" in decoded
    assert 'name="workspace_id"' in decoded
    assert "workspace-core" in decoded
    assert 'name="workflow_reference"' in decoded
    assert "wf-triage" in decoded
    assert 'name="project_reference"' in decoded
    assert "proj-risk" in decoded
    assert 'name="source_connector_metadata"' in decoded
    assert '"connector_id": "connector-1"' in decoded
    assert '"display_name": "Core Claude"' in decoded


def test_build_submission_context_rejects_teams_without_tenant_id():
    with pytest.raises(ValueError, match="tenant_id is required"):
        build_submission_context(
            api_url="https://driftshield.example",
            api_key="secret-key",
            submission_tier="teams",
            tenant_id=None,
            workspace_id=None,
            workflow_reference=None,
            project_reference=None,
            source_connector=SourceConnectorMetadata(),
        )


def test_build_submission_context_uses_server_resolved_tenant_values(monkeypatch):
    def fake_resolve(*, api_url: str, api_key: str, tenant_id: str, workspace_id: str | None):
        assert api_url == "https://driftshield.example"
        assert api_key == "secret-key"
        assert tenant_id == "tenant-claimed"
        assert workspace_id == "workspace-claimed"
        return {
            "tenant_id": "tenant-resolved",
            "workspace_id": "workspace-resolved",
            "service_identity_id": "svc_123",
        }

    monkeypatch.setattr(
        "driftshield.cli.commands.ingest.resolve_teams_submission_context",
        fake_resolve,
    )

    context = build_submission_context(
        api_url="https://driftshield.example",
        api_key="secret-key",
        submission_tier="teams",
        tenant_id="tenant-claimed",
        workspace_id="workspace-claimed",
        workflow_reference="wf-1",
        project_reference="proj-1",
        source_connector=SourceConnectorMetadata(connector_id="connector-1"),
    )

    assert context == SubmissionContext(
        submission_tier="teams",
        tenant_id="tenant-resolved",
        workspace_id="workspace-resolved",
        workflow_reference="wf-1",
        project_reference="proj-1",
        source_connector=SourceConnectorMetadata(connector_id="connector-1"),
    )


def test_ingest_teams_submission_uses_server_resolved_context(monkeypatch):
    captured: dict[str, object] = {}

    def fake_build_submission_context(**kwargs):
        captured["build_kwargs"] = kwargs
        return SubmissionContext(
            submission_tier="teams",
            tenant_id="tenant-resolved",
            workspace_id="workspace-resolved",
        )

    def fake_post_ingest(*, target_url: str, api_key: str, file_path: Path, parser: str, submission_context: SubmissionContext):
        captured["post"] = {
            "target_url": target_url,
            "api_key": api_key,
            "file_path": file_path,
            "parser": parser,
            "submission_context": submission_context,
        }
        return DummyResponse()._payload

    monkeypatch.setenv("DRIFTSHIELD_API_URL", "https://driftshield.example")
    monkeypatch.setenv("DRIFTSHIELD_API_KEY", "secret-key")
    monkeypatch.setattr("driftshield.cli.commands.ingest.build_submission_context", fake_build_submission_context)
    monkeypatch.setattr("driftshield.cli.commands.ingest.post_ingest", fake_post_ingest)

    transcript = FIXTURES_DIR / "sample_claude_code_session.jsonl"
    result = runner.invoke(
        app,
        [
            "ingest",
            "--path",
            str(transcript),
            "--submission-tier",
            "teams",
            "--tenant-id",
            "tenant-claimed",
            "--workspace-id",
            "workspace-claimed",
        ],
    )

    assert result.exit_code == 0
    assert captured["build_kwargs"] == {
        "api_url": "https://driftshield.example",
        "api_key": "secret-key",
        "submission_tier": "teams",
        "tenant_id": "tenant-claimed",
        "workspace_id": "workspace-claimed",
        "workflow_reference": None,
        "project_reference": None,
        "source_connector": SourceConnectorMetadata(
            connector_id=None,
            source_type=None,
            display_name=None,
            parser_name=None,
        ),
    }
    assert captured["post"] == {
        "target_url": "https://driftshield.example/api/ingest",
        "api_key": "secret-key",
        "file_path": transcript,
        "parser": "claude_code",
        "submission_context": SubmissionContext(
            submission_tier="teams",
            tenant_id="tenant-resolved",
            workspace_id="workspace-resolved",
        ),
    }
