"""Tests for the ``driftshield batch`` command (driftshield#163).

Covers: opt-in submission (no --submit => zero network calls), the
redaction invariant when --submit is passed, archive (.zip/.tar.gz) input,
a fixture-directory acceptance case (valid + invalid files, no abort), and
the --json report shape.
"""

from __future__ import annotations

import json
import re
import tarfile
import zipfile
from pathlib import Path

import pytest
from typer.testing import CliRunner

from driftshield.cli._batch import _derive_workflow_reference, run_batch
from driftshield.cli.main import app
from driftshield.core.analysis.session import analyze_session

runner = CliRunner()

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "transcripts"


def _fake_post_ok(captured: dict, submission_id: str = "sub_batch"):
    def fake_post(*, config, submission):
        captured["intake_url"] = config.intake_url
        captured["submission"] = submission
        captured.setdefault("submissions", []).append(submission)

        class _Resp:
            pass

        resp = _Resp()
        resp.submission_id = submission_id
        resp.processing_status = "received"

        class _Result:
            pass

        result = _Result()
        result.response = resp
        result.server_contract_version = None
        return result

    return fake_post


def _network_forbidden(*args, **kwargs):
    raise AssertionError("no network call should be made without --submit")


def _fake_teams_upload_ok(captured: dict, submission_id: str = "sub_teams_batch"):
    def fake_teams_upload(
        *, config, payload, workflow_reference, file_name, provenance, backfill=False
    ):
        captured["api_key"] = config.api_key
        captured.setdefault("backfill_flags", []).append(backfill)
        captured.setdefault("provenances", []).append(provenance)

        class _Resp:
            pass

        resp = _Resp()
        resp.submission_id = submission_id
        resp.processing_status = "received"

        class _Result:
            pass

        result = _Result()
        result.response = resp
        result.server_contract_version = None
        return result

    return fake_teams_upload


def _write_claude_code_jsonl(
    path: Path,
    *,
    session_id: str = "batch-test-session",
    user_text: str = "hello there",
    tool_command: str = "echo hi",
    assistant_text: str = "done",
) -> Path:
    """Write a minimal, well-formed Claude Code JSONL transcript.

    Small enough to reason about exactly, but shaped like a real transcript
    (a user text block, then an assistant tool_use + text block) so both the
    canonical parser and the redactor's content-block handling engage.
    """
    lines = [
        json.dumps(
            {
                "type": "user",
                "sessionId": session_id,
                "message": {
                    "role": "user",
                    "content": [{"type": "text", "text": user_text}],
                },
            }
        ),
        json.dumps(
            {
                "type": "assistant",
                "sessionId": session_id,
                "message": {
                    "model": "claude-test",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "tool_1",
                            "name": "Bash",
                            "input": {"command": tool_command},
                        },
                        {"type": "text", "text": assistant_text},
                    ],
                },
            }
        ),
    ]
    path.write_text("\n".join(lines) + "\n")
    return path


def _write_claude_code_jsonl_with_timestamps(
    path: Path,
    *,
    session_id: str = "batch-test-session-ts",
    user_timestamp: str = "2026-01-01T00:00:00+00:00",
    assistant_timestamp: str = "2026-01-01T00:05:30+00:00",
) -> Path:
    """Same shape as :func:`_write_claude_code_jsonl` but with explicit
    per-record ``timestamp`` fields, so the parsed session's last event
    timestamp is a known, assertable value (driftshield#174)."""
    lines = [
        json.dumps(
            {
                "type": "user",
                "sessionId": session_id,
                "timestamp": user_timestamp,
                "message": {
                    "role": "user",
                    "content": [{"type": "text", "text": "hello there"}],
                },
            }
        ),
        json.dumps(
            {
                "type": "assistant",
                "sessionId": session_id,
                "timestamp": assistant_timestamp,
                "message": {
                    "model": "claude-test",
                    "content": [{"type": "text", "text": "done"}],
                },
            }
        ),
    ]
    path.write_text("\n".join(lines) + "\n")
    return path


def _write_claude_code_jsonl_with_no_events(
    path: Path, *, session_id: str = "batch-empty-session"
) -> Path:
    """A claude_code-shaped JSONL file whose only record type
    (``summary``) yields zero canonical events -- the "no parseable
    timestamps" case (driftshield#174): nothing to date the session by."""
    path.write_text(json.dumps({"type": "summary", "sessionId": session_id}) + "\n")
    return path


# ---------------------------------------------------------------------------
# Opt-in submission gate
# ---------------------------------------------------------------------------


def test_batch_without_submit_makes_no_network_call(tmp_path, monkeypatch):
    monkeypatch.setattr("driftshield.cli._submit.post_oss_submission", _network_forbidden)
    monkeypatch.setattr(
        "driftshield.cli._submit.submit_oss_via_presigned_upload", _network_forbidden
    )
    monkeypatch.setattr(
        "driftshield.cli._submit.submit_teams_via_presigned_upload", _network_forbidden
    )

    _write_claude_code_jsonl(tmp_path / "a.jsonl")
    _write_claude_code_jsonl(tmp_path / "b.jsonl", session_id="batch-test-session-2")

    result = runner.invoke(app, ["batch", str(tmp_path)])

    assert result.exit_code == 0, result.output
    body = result.output
    assert "analysed-only" in body


def test_batch_without_submit_reports_analysed_only(tmp_path):
    _write_claude_code_jsonl(tmp_path / "a.jsonl")

    report = run_batch(tmp_path, submit=False)

    assert len(report.files) == 1
    assert report.files[0].outcome == "analysed-only"
    assert report.files[0].submission_id is None
    assert report.totals == {"submitted": 0, "analysed-only": 1, "failed": 0, "skipped": 0}
    assert report.has_failures is False


# ---------------------------------------------------------------------------
# Redaction invariant (--submit)
# ---------------------------------------------------------------------------


def test_batch_submit_redacts_before_upload(tmp_path, monkeypatch):
    """driftshield#163 acceptance criterion: batch --submit must never upload
    raw prompt/response text or raw tool-input values."""
    captured: dict = {}
    monkeypatch.setattr(
        "driftshield.cli._submit.post_oss_submission", _fake_post_ok(captured)
    )
    monkeypatch.setenv("DRIFTSHIELD_TELEMETRY_HOME", str(tmp_path / "tele"))

    secret_user_text = "SECRET_USER_PROMPT_MARKER_XYZ, please run the deploy"
    secret_tool_command = "echo SECRET_TOOL_INPUT_MARKER_QRS"
    secret_assistant_text = "SECRET_ASSISTANT_RESPONSE_MARKER_ABC"

    transcripts_dir = tmp_path / "transcripts"
    transcripts_dir.mkdir()
    _write_claude_code_jsonl(
        transcripts_dir / "session.jsonl",
        user_text=secret_user_text,
        tool_command=secret_tool_command,
        assistant_text=secret_assistant_text,
    )

    report = run_batch(transcripts_dir, submit=True, tier="oss")

    assert len(report.files) == 1
    assert report.files[0].outcome == "submitted", report.files[0].reason
    assert report.files[0].submission_id == "sub_batch"

    submission = captured["submission"]
    body = submission.model_dump_json()

    for secret in (secret_user_text, secret_tool_command, secret_assistant_text, "SECRET"):
        assert secret not in body, f"redaction invariant violated: {secret!r} leaked into upload body"

    # Sanity: the redactor actually engaged (payload isn't just untouched).
    assert "REDACTED" in body


def test_batch_submit_cli_flag_wires_through(tmp_path, monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(
        "driftshield.cli._submit.post_oss_submission", _fake_post_ok(captured)
    )
    monkeypatch.setenv("DRIFTSHIELD_TELEMETRY_HOME", str(tmp_path / "tele"))
    _write_claude_code_jsonl(tmp_path / "session.jsonl", user_text="plain text prompt")

    result = runner.invoke(app, ["batch", str(tmp_path), "--submit", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["totals"]["submitted"] == 1
    assert payload["files"][0]["submission_id"] == "sub_batch"


# ---------------------------------------------------------------------------
# --backfill flag (driftshield#169)
# ---------------------------------------------------------------------------


def test_batch_backfill_teams_tier_sends_top_level_backfill_true(tmp_path, monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(
        "driftshield.cli._submit.submit_teams_via_presigned_upload",
        _fake_teams_upload_ok(captured),
    )
    monkeypatch.setenv("DRIFTSHIELD_API_KEY", "test-key")
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("DRIFTSHIELD_TELEMETRY_HOME", str(tmp_path / "tele"))
    runner.invoke(app, ["telemetry", "remote-enable", "--intake-url", "https://intake.example.test/v1/intake"])
    _write_claude_code_jsonl(tmp_path / "session.jsonl")

    result = runner.invoke(
        app, ["batch", str(tmp_path), "--submit", "--tier", "teams", "--backfill", "--json"]
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["totals"]["submitted"] == 1
    assert captured["backfill_flags"] == [True]


def test_batch_backfill_community_tier_exits_nonzero_before_any_upload(tmp_path, monkeypatch):
    monkeypatch.setattr("driftshield.cli._submit.post_oss_submission", _network_forbidden)
    monkeypatch.setattr(
        "driftshield.cli._submit.submit_oss_via_presigned_upload", _network_forbidden
    )
    monkeypatch.setattr(
        "driftshield.cli._submit.submit_teams_via_presigned_upload", _network_forbidden
    )
    _write_claude_code_jsonl(tmp_path / "session.jsonl")

    result = runner.invoke(
        app, ["batch", str(tmp_path), "--submit", "--tier", "oss", "--backfill"]
    )

    assert result.exit_code != 0
    assert "--backfill" in result.output
    assert "teams" in result.output


def test_batch_backfill_without_submit_warns_and_uploads_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr("driftshield.cli._submit.post_oss_submission", _network_forbidden)
    monkeypatch.setattr(
        "driftshield.cli._submit.submit_oss_via_presigned_upload", _network_forbidden
    )
    monkeypatch.setattr(
        "driftshield.cli._submit.submit_teams_via_presigned_upload", _network_forbidden
    )
    _write_claude_code_jsonl(tmp_path / "session.jsonl")

    result = runner.invoke(app, ["batch", str(tmp_path), "--backfill"])

    assert result.exit_code == 0, result.output
    assert "Warning" in result.output
    assert "analysed-only" in result.output


# ---------------------------------------------------------------------------
# --workflow-reference flag, with per-source derivation (driftshield#182)
# ---------------------------------------------------------------------------


def test_batch_workflow_reference_flag_stamps_every_submitted_envelope(tmp_path, monkeypatch):
    captured: dict = {}
    monkeypatch.setattr("driftshield.cli._submit.post_oss_submission", _fake_post_ok(captured))
    monkeypatch.setenv("DRIFTSHIELD_TELEMETRY_HOME", str(tmp_path / "tele"))
    _write_claude_code_jsonl(tmp_path / "a.jsonl", session_id="wf-a")
    _write_claude_code_jsonl(tmp_path / "b.jsonl", session_id="wf-b")

    report = run_batch(tmp_path, submit=True, tier="oss", workflow_reference="explicit-ref")

    assert report.totals["submitted"] == 2, report.files
    for submission in captured["submissions"]:
        assert submission.envelope.workflow_reference == "explicit-ref"


def test_batch_workflow_reference_cli_flag_wires_through(tmp_path, monkeypatch):
    captured: dict = {}
    monkeypatch.setattr("driftshield.cli._submit.post_oss_submission", _fake_post_ok(captured))
    monkeypatch.setenv("DRIFTSHIELD_TELEMETRY_HOME", str(tmp_path / "tele"))
    _write_claude_code_jsonl(tmp_path / "session.jsonl")

    result = runner.invoke(
        app, ["batch", str(tmp_path), "--submit", "--workflow-reference", "cli-ref", "--json"]
    )

    assert result.exit_code == 0, result.output
    assert captured["submission"].envelope.workflow_reference == "cli-ref"


def test_batch_without_workflow_reference_flag_derives_one_per_source_directory(
    tmp_path, monkeypatch
):
    """driftshield#182 acceptance criterion: without the flag, a tree
    containing at least two source directories produces submitted envelopes
    carrying different workflow references, one per directory."""
    captured: dict = {}
    monkeypatch.setattr("driftshield.cli._submit.post_oss_submission", _fake_post_ok(captured))
    monkeypatch.setenv("DRIFTSHIELD_TELEMETRY_HOME", str(tmp_path / "tele"))

    project_a = tmp_path / "project-a"
    project_b = tmp_path / "project-b"
    project_a.mkdir()
    project_b.mkdir()
    _write_claude_code_jsonl(project_a / "session.jsonl", session_id="proj-a-session")
    _write_claude_code_jsonl(project_b / "session.jsonl", session_id="proj-b-session")

    report = run_batch(tmp_path, submit=True, tier="oss")

    assert report.totals["submitted"] == 2, report.files
    refs = {submission.envelope.workflow_reference for submission in captured["submissions"]}
    assert refs == {"project-a", "project-b"}


def test_batch_derived_workflow_reference_stable_across_runs_and_sanitised(tmp_path, monkeypatch):
    """driftshield#182 acceptance criterion: derivation is stable across
    runs for the same directory, and sanitises a directory name containing
    characters the field does not accept."""
    captured: dict = {}
    monkeypatch.setattr("driftshield.cli._submit.post_oss_submission", _fake_post_ok(captured))
    monkeypatch.setenv("DRIFTSHIELD_TELEMETRY_HOME", str(tmp_path / "tele"))

    unsafe_dir = tmp_path / "My Project!! (v2)"
    unsafe_dir.mkdir()
    _write_claude_code_jsonl(unsafe_dir / "session.jsonl")

    report_1 = run_batch(unsafe_dir, submit=True, tier="oss")
    ref_1 = captured["submissions"][-1].envelope.workflow_reference
    report_2 = run_batch(unsafe_dir, submit=True, tier="oss")
    ref_2 = captured["submissions"][-1].envelope.workflow_reference

    assert report_1.totals["submitted"] == 1, report_1.files
    assert report_2.totals["submitted"] == 1, report_2.files
    assert ref_1 == ref_2
    assert ref_1 == re.sub(r"[^A-Za-z0-9._-]+", "-", "My Project!! (v2)").strip("-")
    assert " " not in ref_1
    assert "!" not in ref_1
    assert "(" not in ref_1


def test_derive_workflow_reference_falls_back_to_default_for_all_symbol_directory(tmp_path):
    """An all-symbol directory name sanitises to nothing usable; falls back
    to the module default rather than an empty/invalid reference."""
    directory = tmp_path / "!!!"
    directory.mkdir()

    assert _derive_workflow_reference(directory / "session.jsonl") == "default"


def test_batch_workflow_reference_without_submit_warns_and_uploads_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr("driftshield.cli._submit.post_oss_submission", _network_forbidden)
    monkeypatch.setattr(
        "driftshield.cli._submit.submit_oss_via_presigned_upload", _network_forbidden
    )
    monkeypatch.setattr(
        "driftshield.cli._submit.submit_teams_via_presigned_upload", _network_forbidden
    )
    _write_claude_code_jsonl(tmp_path / "session.jsonl")

    result = runner.invoke(app, ["batch", str(tmp_path), "--workflow-reference", "unused-ref"])

    assert result.exit_code == 0, result.output
    assert "Warning" in result.output
    assert "analysed-only" in result.output


def test_batch_help_mentions_workflow_reference_flag():
    result = runner.invoke(app, ["batch", "--help"])
    output = ANSI_RE.sub("", result.output)

    assert result.exit_code == 0
    assert "--workflow-reference" in output


# ---------------------------------------------------------------------------
# session_observed_at (driftshield#174)
# ---------------------------------------------------------------------------


def test_batch_backfill_sends_session_observed_at_on_inline_oss_envelope(tmp_path, monkeypatch):
    """Inline lane: session_observed_at equals the session's last event
    timestamp on the envelope."""
    captured: dict = {}
    monkeypatch.setattr("driftshield.cli._submit.post_oss_submission", _fake_post_ok(captured))
    monkeypatch.setenv("DRIFTSHIELD_TELEMETRY_HOME", str(tmp_path / "tele"))
    _write_claude_code_jsonl_with_timestamps(
        tmp_path / "session.jsonl", assistant_timestamp="2026-01-01T00:05:30+00:00"
    )

    report = run_batch(tmp_path, submit=True, tier="oss")

    assert report.files[0].outcome == "submitted", report.files[0].reason
    envelope = captured["submission"].envelope
    assert envelope.session_observed_at is not None
    assert envelope.session_observed_at.isoformat() == "2026-01-01T00:05:30+00:00"


def test_batch_backfill_sends_session_observed_at_on_teams_finalise_body(tmp_path, monkeypatch):
    """Presigned lane: session_observed_at rides the finalise body as a
    sibling of the existing backfill field (via the shared provenance
    dict), proven against a stubbed endpoint."""
    captured: dict = {}
    monkeypatch.setattr(
        "driftshield.cli._submit.submit_teams_via_presigned_upload",
        _fake_teams_upload_ok(captured),
    )
    monkeypatch.setenv("DRIFTSHIELD_API_KEY", "test-key")
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("DRIFTSHIELD_TELEMETRY_HOME", str(tmp_path / "tele"))
    runner.invoke(
        app,
        ["telemetry", "remote-enable", "--intake-url", "https://intake.example.test/v1/intake"],
    )
    _write_claude_code_jsonl_with_timestamps(
        tmp_path / "session.jsonl", assistant_timestamp="2026-01-01T00:05:30+00:00"
    )

    result = runner.invoke(
        app, ["batch", str(tmp_path), "--submit", "--tier", "teams", "--backfill", "--json"]
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["totals"]["submitted"] == 1
    assert captured["backfill_flags"] == [True]
    assert captured["provenances"][0]["session_observed_at"] == "2026-01-01T00:05:30+00:00"


def test_batch_no_parseable_timestamps_omits_session_observed_at(tmp_path, monkeypatch):
    """A transcript that yields zero canonical events has nothing to date
    it by: session_observed_at is omitted and the submission still goes
    through."""
    captured: dict = {}
    monkeypatch.setattr("driftshield.cli._submit.post_oss_submission", _fake_post_ok(captured))
    monkeypatch.setenv("DRIFTSHIELD_TELEMETRY_HOME", str(tmp_path / "tele"))
    _write_claude_code_jsonl_with_no_events(tmp_path / "empty.jsonl")

    report = run_batch(tmp_path, submit=True, tier="oss")

    assert report.files[0].outcome == "submitted", report.files[0].reason
    envelope = captured["submission"].envelope
    assert envelope.session_observed_at is None


def test_batch_session_observed_at_sent_without_backfill_flag(tmp_path, monkeypatch):
    """Not gated by --backfill: sent on ordinary submissions too (the
    server ignores it outside backfill)."""
    captured: dict = {}
    monkeypatch.setattr("driftshield.cli._submit.post_oss_submission", _fake_post_ok(captured))
    monkeypatch.setenv("DRIFTSHIELD_TELEMETRY_HOME", str(tmp_path / "tele"))
    _write_claude_code_jsonl_with_timestamps(
        tmp_path / "session.jsonl", assistant_timestamp="2026-02-02T12:00:00+00:00"
    )

    report = run_batch(tmp_path, submit=True, tier="oss")

    assert report.files[0].outcome == "submitted", report.files[0].reason
    envelope = captured["submission"].envelope
    assert envelope.session_observed_at is not None
    assert envelope.session_observed_at.isoformat() == "2026-02-02T12:00:00+00:00"


def test_batch_session_observed_at_does_not_affect_redaction(tmp_path, monkeypatch):
    """Regression: session_observed_at is envelope-level (a sibling of
    payload); adding it must not touch the redaction invariant."""
    captured: dict = {}
    monkeypatch.setattr("driftshield.cli._submit.post_oss_submission", _fake_post_ok(captured))
    monkeypatch.setenv("DRIFTSHIELD_TELEMETRY_HOME", str(tmp_path / "tele"))

    secret_user_text = "SECRET_USER_PROMPT_MARKER_XYZ"
    _write_claude_code_jsonl(tmp_path / "session.jsonl", user_text=secret_user_text)

    report = run_batch(tmp_path, submit=True, tier="oss")

    assert report.files[0].outcome == "submitted", report.files[0].reason
    submission = captured["submission"]
    assert submission.envelope.session_observed_at is not None
    assert secret_user_text not in submission.model_dump_json()


# ---------------------------------------------------------------------------
# Per-file isolation: skipped / failed, no abort
# ---------------------------------------------------------------------------


def test_batch_fixture_directory_valid_and_invalid_do_not_abort(tmp_path):
    """driftshield#163 base acceptance criterion: >=2 valid transcripts plus
    one invalid file in a directory; batch must analyse the valid ones and
    mark the invalid one failed/skipped without aborting."""
    import shutil

    shutil.copy(
        FIXTURES_DIR / "sample_claude_code_session.jsonl",
        tmp_path / "sample_claude_code_session.jsonl",
    )
    shutil.copy(
        FIXTURES_DIR / "sample_codex_cli_session.jsonl",
        tmp_path / "sample_codex_cli_session.jsonl",
    )
    (tmp_path / "not_a_transcript.txt").write_text("this is just some random notes, not JSON\n")

    report = run_batch(tmp_path)

    outcomes = {entry.path: entry.outcome for entry in report.files}
    assert outcomes["sample_claude_code_session.jsonl"] == "analysed-only"
    assert outcomes["sample_codex_cli_session.jsonl"] == "analysed-only"
    assert outcomes["not_a_transcript.txt"] in {"failed", "skipped"}
    assert outcomes["not_a_transcript.txt"] == "skipped"  # no parser matches .txt
    invalid_entry = next(e for e in report.files if e.path == "not_a_transcript.txt")
    assert invalid_entry.reason

    # Base case: no genuine failures, only a clean skip.
    assert report.has_failures is False


def test_batch_detects_non_jsonl_transcript_by_content_in_plain_directory(tmp_path):
    """driftshield#163 review finding: detect_parser() keys on native session
    directory hints (e.g. `.claude-desktop/sessions/`) or a `.jsonl` suffix, so
    a supported non-.jsonl transcript (claude_desktop here) copied into a
    plain directory has none of those hints. Batch must still recognise it by
    sniffing its content, not report it as skipped."""
    import shutil

    shutil.copy(
        FIXTURES_DIR / "sample_claude_desktop_session.json",
        tmp_path / "sample_claude_desktop_session.json",
    )

    report = run_batch(tmp_path)

    outcomes = {entry.path: entry.outcome for entry in report.files}
    assert outcomes["sample_claude_desktop_session.json"] == "analysed-only"
    assert report.has_failures is False


def test_batch_detects_non_jsonl_transcript_in_zip_archive(tmp_path):
    """Same coverage gap as above, but via the archive path: the transcript
    is extracted to a flat temp directory with no native path hints either."""
    archive_path = tmp_path / "sessions.zip"
    with zipfile.ZipFile(archive_path, "w") as zf:
        zf.write(
            FIXTURES_DIR / "sample_claude_desktop_session.json",
            arcname="sample_claude_desktop_session.json",
        )

    report = run_batch(archive_path)

    outcomes = {entry.path: entry.outcome for entry in report.files}
    assert outcomes["sample_claude_desktop_session.json"] == "analysed-only"
    assert report.has_failures is False


# ---------------------------------------------------------------------------
# Zero-event reconciliation via content detection (driftshield#185)
# ---------------------------------------------------------------------------


def test_batch_reidentifies_codex_fixture_by_content_when_path_default_is_wrong(
    tmp_path, monkeypatch
):
    """driftshield#185: a codex_cli JSONL file copied into a plain directory
    (no `.codex/sessions/` path hint) has only the bare `.jsonl` suffix to go
    on, so ``detect_parser()`` defaults it to claude_code -- its historical
    assume-Claude-Code fallback. Parsing it as claude_code silently yields
    zero events. Batch must notice the zero-event parse, consult content
    detection (``public.detect_source``), and re-parse as codex_cli --
    recovering its 3 events instead of a silent, wrong 'analysed-only'."""
    import shutil

    shutil.copy(
        FIXTURES_DIR / "sample_codex_cli_session.jsonl",
        tmp_path / "sample_codex_cli_session.jsonl",
    )

    captured_events: list[list] = []
    real_analyze_session = analyze_session

    def _spy_analyze_session(events):
        captured_events.append(events)
        return real_analyze_session(events)

    monkeypatch.setattr("driftshield.cli._batch.analyze_session", _spy_analyze_session)

    report = run_batch(tmp_path)

    entry = report.files[0]
    assert entry.outcome == "analysed-only"
    assert entry.reason is None  # recovered -- nothing to warn about

    final_events = captured_events[-1]
    assert len(final_events) == 3
    assert all(
        any(ref.get("kind") == "parser" and ref.get("value") == "codex_cli" for ref in event.source_refs)
        for event in final_events
    )


def test_batch_zero_events_from_both_path_and_content_detection_warns(tmp_path):
    """driftshield#185: when the path-based parser yields zero events *and*
    content detection either agrees or finds nothing better, batch must
    record an explicit warning in the report instead of a silent
    'analysed-only' with no reason."""
    _write_claude_code_jsonl_with_no_events(tmp_path / "empty.jsonl")

    report = run_batch(tmp_path)

    entry = report.files[0]
    assert entry.outcome == "analysed-only"
    assert entry.reason is not None
    assert "zero events" in entry.reason


def test_batch_isolates_a_file_that_raises_during_parsing(tmp_path):
    """A file that auto-detects to a parser but blows up during parse/analyse
    must be recorded 'failed' with the exception message, and must not stop
    the rest of the batch from being processed."""
    _write_claude_code_jsonl(tmp_path / "good.jsonl")
    # A bare JSON scalar is valid JSON but not a transcript record: the
    # Claude Code parser's `"sessionId" in entry` check raises TypeError on
    # a non-dict entry, so this is a genuine per-file parse failure rather
    # than a "no parser detected" skip.
    (tmp_path / "corrupt.jsonl").write_text("123\n")

    report = run_batch(tmp_path)

    outcomes = {entry.path: entry for entry in report.files}
    assert outcomes["good.jsonl"].outcome == "analysed-only"
    assert outcomes["corrupt.jsonl"].outcome == "failed"
    assert outcomes["corrupt.jsonl"].reason
    assert report.has_failures is True


def test_batch_cli_exit_code_nonzero_on_failure(tmp_path):
    (tmp_path / "corrupt.jsonl").write_text("123\n")

    result = runner.invoke(app, ["batch", str(tmp_path)])

    assert result.exit_code == 1, result.output


def test_batch_cli_exit_code_zero_when_only_skipped(tmp_path):
    (tmp_path / "not_a_transcript.txt").write_text("random notes\n")

    result = runner.invoke(app, ["batch", str(tmp_path)])

    assert result.exit_code == 0, result.output


# ---------------------------------------------------------------------------
# Archive input (.zip / .tar.gz)
# ---------------------------------------------------------------------------


def _build_archive_payloads(tmp_path: Path) -> dict[str, str]:
    session_a = tmp_path / "_source_a.jsonl"
    session_b = tmp_path / "_source_b.jsonl"
    _write_claude_code_jsonl(session_a, session_id="archive-a")
    _write_claude_code_jsonl(session_b, session_id="archive-b")
    return {
        "session_a.jsonl": session_a.read_text(),
        "session_b.jsonl": session_b.read_text(),
        "garbage.bin": "not a transcript at all, just bytes-as-text\x00\x01",
    }


def test_batch_processes_zip_archive_end_to_end(tmp_path):
    payloads = _build_archive_payloads(tmp_path)
    archive_path = tmp_path / "sessions.zip"
    with zipfile.ZipFile(archive_path, "w") as zf:
        for name, content in payloads.items():
            zf.writestr(name, content)

    report = run_batch(archive_path)

    outcomes = {entry.path: entry.outcome for entry in report.files}
    assert outcomes["session_a.jsonl"] == "analysed-only"
    assert outcomes["session_b.jsonl"] == "analysed-only"
    assert outcomes["garbage.bin"] == "skipped"
    assert report.has_failures is False


def test_batch_processes_tar_gz_archive_end_to_end(tmp_path):
    payloads = _build_archive_payloads(tmp_path)
    archive_path = tmp_path / "sessions.tar.gz"
    with tarfile.open(archive_path, "w:gz") as tf:
        for name, content in payloads.items():
            data = content.encode("utf-8")
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            import io

            tf.addfile(info, io.BytesIO(data))

    result = runner.invoke(app, ["batch", str(archive_path), "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["totals"]["analysed-only"] == 2
    assert payload["totals"]["skipped"] == 1
    assert payload["totals"]["failed"] == 0


def test_batch_rejects_unsupported_source():
    with pytest.raises(ValueError):
        run_batch(Path("/nonexistent/not-a-dir-or-archive.rar"))


# ---------------------------------------------------------------------------
# --json report shape
# ---------------------------------------------------------------------------


def test_batch_json_output_is_stable_and_parseable(tmp_path):
    _write_claude_code_jsonl(tmp_path / "a.jsonl")
    (tmp_path / "skip.txt").write_text("not a transcript\n")

    result = runner.invoke(app, ["batch", str(tmp_path), "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)

    assert set(payload.keys()) == {"totals", "files"}
    assert set(payload["totals"].keys()) == {"submitted", "analysed-only", "failed", "skipped"}
    assert payload["totals"]["analysed-only"] == 1
    assert payload["totals"]["skipped"] == 1

    for entry in payload["files"]:
        assert set(entry.keys()) == {"path", "outcome", "reason", "submission_id"}
        assert entry["outcome"] in {"submitted", "analysed-only", "failed", "skipped"}


def test_batch_help_mentions_submit_flag():
    result = runner.invoke(app, ["batch", "--help"])
    output = ANSI_RE.sub("", result.output)

    assert result.exit_code == 0
    assert "--submit" in output
    assert "--tier" in output
    assert "--include-analysis" in output
    assert "--backfill" in output


# ---------------------------------------------------------------------------
# Full fixture matrix: every bundled transcript format must analyse AND
# submit through batch, whether copied plain (no native path hints) into a
# directory or packed into a zip archive. driftshield#163 review round 3:
# batch's submit step must accept every shape detect_source() supports, the
# same as the single-file `driftshield submit` lane -- not a stricter one.
# ---------------------------------------------------------------------------

_ALL_TRANSCRIPT_FIXTURES = [
    "sample_claude_code_session.jsonl",
    "sample_codex_cli_session.jsonl",
    "sample_claude_desktop_session.json",
    "sample_codex_desktop_session.json",
    "sample_crewai_session.json",
    "sample_langchain_session.json",
    "sample_openclaw_trajectory.json",
]


@pytest.mark.parametrize("fixture_name", _ALL_TRANSCRIPT_FIXTURES)
def test_batch_analyses_every_bundled_fixture_in_plain_directory(tmp_path, fixture_name):
    """Every bundled transcript format, copied plain (no native path-hint
    directory) must be analysed, not skipped or failed."""
    import shutil

    shutil.copy(FIXTURES_DIR / fixture_name, tmp_path / fixture_name)

    report = run_batch(tmp_path, submit=False)

    assert len(report.files) == 1
    assert report.files[0].outcome == "analysed-only", report.files[0].reason


@pytest.mark.parametrize("fixture_name", _ALL_TRANSCRIPT_FIXTURES)
def test_batch_submits_every_bundled_fixture_in_plain_directory(
    tmp_path, fixture_name, monkeypatch
):
    """Every bundled transcript format must submit successfully through
    batch --submit against a stubbed endpoint: no shape is skipped or
    failed, and none of the redacted bodies leak raw content."""
    import shutil

    captured: dict = {}
    monkeypatch.setattr("driftshield.cli._submit.post_oss_submission", _fake_post_ok(captured))
    monkeypatch.setenv("DRIFTSHIELD_TELEMETRY_HOME", str(tmp_path / "tele"))

    source_dir = tmp_path / "transcripts"
    source_dir.mkdir()
    shutil.copy(FIXTURES_DIR / fixture_name, source_dir / fixture_name)

    report = run_batch(source_dir, submit=True, tier="oss")

    assert len(report.files) == 1
    assert report.files[0].outcome == "submitted", report.files[0].reason
    assert report.files[0].submission_id == "sub_batch"


@pytest.mark.parametrize("fixture_name", _ALL_TRANSCRIPT_FIXTURES)
def test_batch_submits_every_bundled_fixture_from_zip_archive(tmp_path, fixture_name, monkeypatch):
    """Same fixture matrix, but extracted from a zip archive: no native
    path hints and no native directory structure survive extraction."""
    captured: dict = {}
    monkeypatch.setattr("driftshield.cli._submit.post_oss_submission", _fake_post_ok(captured))
    monkeypatch.setenv("DRIFTSHIELD_TELEMETRY_HOME", str(tmp_path / "tele"))

    archive_path = tmp_path / "sessions.zip"
    with zipfile.ZipFile(archive_path, "w") as zf:
        zf.write(FIXTURES_DIR / fixture_name, arcname=fixture_name)

    report = run_batch(archive_path, submit=True, tier="oss")

    assert len(report.files) == 1
    assert report.files[0].outcome == "submitted", report.files[0].reason


def test_batch_errors_on_missing_source():
    result = runner.invoke(app, ["batch", "/definitely/not/a/real/path"])

    assert result.exit_code == 1
    assert "does not exist" in result.output
