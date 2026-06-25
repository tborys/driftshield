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


def test_build_multipart_body_includes_oss_tier_and_source_connector_metadata():
    transcript = FIXTURES_DIR / "sample_claude_code_session.jsonl"

    body = _build_multipart_body(
        boundary="test-boundary",
        file_path=transcript,
        parser="claude_code",
        submission_context=SubmissionContext(
            submission_tier="oss",
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
    assert "oss" in decoded
    assert 'name="tenant_id"' not in decoded
    assert 'name="workspace_id"' not in decoded
    assert 'name="workflow_reference"' in decoded
    assert "wf-triage" in decoded
    assert 'name="project_reference"' in decoded
    assert "proj-risk" in decoded
    assert 'name="source_connector_metadata"' in decoded
    assert '"connector_id": "connector-1"' in decoded
    assert '"display_name": "Core Claude"' in decoded


def test_ingest_has_no_teams_options():
    result = runner.invoke(app, ["ingest", "--help"])
    assert "--submission-tier" not in result.output
    assert "--tenant-id" not in result.output
    assert "--workspace-id" not in result.output


def test_resolve_teams_submission_context_is_gone():
    import driftshield.cli.commands.ingest as ingest_mod
    assert not hasattr(ingest_mod, "resolve_teams_submission_context")


# ---------------------------------------------------------------------------
# --include-analysis flag on ingest
# ---------------------------------------------------------------------------


def test_ingest_default_no_signature_summary(monkeypatch):
    """Default invocation does not attach a signature_summary form field."""
    captured: dict[str, object] = {}

    def fake_post_ingest(*, target_url, api_key, file_path, parser, submission_context):  # noqa: ARG001
        captured["submission_context"] = submission_context
        return DummyResponse()._payload

    monkeypatch.setenv("DRIFTSHIELD_API_URL", "http://localhost:8000")
    monkeypatch.setenv("DRIFTSHIELD_API_KEY", "test-key")
    monkeypatch.setattr("driftshield.cli.commands.ingest.post_ingest", fake_post_ingest)

    transcript = FIXTURES_DIR / "sample_claude_code_session.jsonl"
    result = runner.invoke(app, ["ingest", "--path", str(transcript)])

    assert result.exit_code == 0
    context = captured["submission_context"]
    assert isinstance(context, SubmissionContext)
    assert context.signature_summary_json is None


def test_ingest_with_include_analysis_attaches_signature_summary(monkeypatch):
    """--include-analysis populates SubmissionContext.signature_summary_json."""
    from driftshield.intake_contract import (
        SIGNATURE_SUMMARY_VERSION,
        SignatureSummary,
        SignatureSummaryEntry,
    )

    fake_summary = SignatureSummary(
        schema_version=SIGNATURE_SUMMARY_VERSION,
        matches=[
            SignatureSummaryEntry(
                signature_id="sig-abc",
                match_status="matched",
                community_pack_id="community-general",
                community_pack_version="1.0.0",
                matcher_id="phase-3g-deterministic-v1",
                matcher_version="phase-3g-deterministic-rules-v1",
                confidence=0.9,
                confidence_band="high",
            )
        ],
    )

    captured: dict[str, object] = {}

    def fake_post_ingest(*, target_url, api_key, file_path, parser, submission_context):  # noqa: ARG001
        captured["submission_context"] = submission_context
        return DummyResponse()._payload

    monkeypatch.setenv("DRIFTSHIELD_API_URL", "http://localhost:8000")
    monkeypatch.setenv("DRIFTSHIELD_API_KEY", "test-key")
    monkeypatch.setattr("driftshield.cli.commands.ingest.post_ingest", fake_post_ingest)
    monkeypatch.setattr(
        "driftshield.cli._signature_summary.build_signature_summary_from_session",
        lambda _path: fake_summary,
    )

    transcript = FIXTURES_DIR / "sample_claude_code_session.jsonl"
    result = runner.invoke(
        app, ["ingest", "--path", str(transcript), "--include-analysis"]
    )

    assert result.exit_code == 0
    context = captured["submission_context"]
    assert isinstance(context, SubmissionContext)
    assert context.signature_summary_json is not None
    decoded = json.loads(context.signature_summary_json)
    assert decoded["schema_version"] == SIGNATURE_SUMMARY_VERSION
    assert decoded["matches"][0]["signature_id"] == "sig-abc"


def test_ingest_include_analysis_strict_fail_on_builder_error(monkeypatch):
    """--include-analysis is strict: any builder exception fails the command.

    The ingest POST MUST NOT happen and the exit code MUST be non-zero so the
    operator notices that the explicit opt-in could not be honoured.
    """
    posted = {"called": False}

    def fake_post_ingest(*, target_url, api_key, file_path, parser, submission_context):  # noqa: ARG001
        posted["called"] = True
        return DummyResponse()._payload

    def boom(_path):
        raise RuntimeError("matcher exploded")

    monkeypatch.setenv("DRIFTSHIELD_API_URL", "http://localhost:8000")
    monkeypatch.setenv("DRIFTSHIELD_API_KEY", "test-key")
    monkeypatch.setattr("driftshield.cli.commands.ingest.post_ingest", fake_post_ingest)
    monkeypatch.setattr(
        "driftshield.cli._signature_summary.build_signature_summary_from_session",
        boom,
    )

    transcript = FIXTURES_DIR / "sample_claude_code_session.jsonl"
    result = runner.invoke(
        app, ["ingest", "--path", str(transcript), "--include-analysis"]
    )

    assert result.exit_code != 0
    assert posted["called"] is False
    assert "build_signature_summary_from_session" in result.stderr
    assert "matcher exploded" in result.stderr


def test_ingest_include_analysis_empty_matches_is_valid_success(monkeypatch):
    """An empty matches list IS a valid success path under --include-analysis.

    Zero matches is not a builder failure: the multipart upload proceeds with
    the empty SignatureSummary attached as the signature_summary form field.
    """
    from driftshield.intake_contract import (
        SIGNATURE_SUMMARY_VERSION,
        SignatureSummary,
    )

    empty_summary = SignatureSummary(
        schema_version=SIGNATURE_SUMMARY_VERSION,
        matches=[],
    )

    captured: dict[str, object] = {}

    def fake_post_ingest(*, target_url, api_key, file_path, parser, submission_context):  # noqa: ARG001
        captured["submission_context"] = submission_context
        return DummyResponse()._payload

    monkeypatch.setenv("DRIFTSHIELD_API_URL", "http://localhost:8000")
    monkeypatch.setenv("DRIFTSHIELD_API_KEY", "test-key")
    monkeypatch.setattr("driftshield.cli.commands.ingest.post_ingest", fake_post_ingest)
    monkeypatch.setattr(
        "driftshield.cli._signature_summary.build_signature_summary_from_session",
        lambda _path: empty_summary,
    )

    transcript = FIXTURES_DIR / "sample_claude_code_session.jsonl"
    result = runner.invoke(
        app, ["ingest", "--path", str(transcript), "--include-analysis"]
    )

    assert result.exit_code == 0
    context = captured["submission_context"]
    assert isinstance(context, SubmissionContext)
    assert context.signature_summary_json is not None
    decoded = json.loads(context.signature_summary_json)
    assert decoded["schema_version"] == SIGNATURE_SUMMARY_VERSION
    assert decoded["matches"] == []


def test_build_multipart_body_includes_signature_summary_field():
    """signature_summary form field is written when SubmissionContext carries it."""
    transcript = FIXTURES_DIR / "sample_claude_code_session.jsonl"

    summary_json = '{"schema_version": "signature-summary.v1", "matches": []}'
    body = _build_multipart_body(
        boundary="test-boundary",
        file_path=transcript,
        parser="claude_code",
        submission_context=SubmissionContext(
            submission_tier="oss",
            signature_summary_json=summary_json,
        ),
    )

    decoded = body.decode("utf-8", errors="ignore")
    assert 'name="signature_summary"' in decoded
    assert "signature-summary.v1" in decoded


def test_build_multipart_body_omits_signature_summary_when_absent():
    """No signature_summary field appears when SubmissionContext.signature_summary_json is None."""
    transcript = FIXTURES_DIR / "sample_claude_code_session.jsonl"

    body = _build_multipart_body(
        boundary="test-boundary",
        file_path=transcript,
        parser="claude_code",
        submission_context=SubmissionContext(submission_tier="oss"),
    )

    decoded = body.decode("utf-8", errors="ignore")
    assert 'name="signature_summary"' not in decoded
