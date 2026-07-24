"""Tests for the ``driftshield batch`` command (driftshield#163).

Covers: opt-in submission (no --submit => zero network calls), the
redaction invariant when --submit is passed, archive (.zip/.tar.gz) input,
a fixture-directory acceptance case (valid + invalid files, no abort), and
the --json report shape.
"""

from __future__ import annotations

import json
import tarfile
import zipfile
from pathlib import Path

import pytest
from typer.testing import CliRunner

from driftshield.cli._batch import run_batch
from driftshield.cli.main import app

runner = CliRunner()

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

    assert result.exit_code == 0
    assert "--submit" in result.output
    assert "--tier" in result.output
    assert "--include-analysis" in result.output


def test_batch_errors_on_missing_source():
    result = runner.invoke(app, ["batch", "/definitely/not/a/real/path"])

    assert result.exit_code == 1
    assert "does not exist" in result.output
