from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from driftshield.cli.main import app

runner = CliRunner()


def _write_session(tmp_path: Path) -> Path:
    # Minimal OpenClaw-shaped session the redactor recognises.
    session = {
        "events": [
            {"type": "session", "session_id": "s1"},
            {"type": "message", "message": {"role": "user", "content": [{"type": "text", "text": "hi"}]}},
        ],
        "metadata": {},
    }
    p = tmp_path / "session.json"
    p.write_text(json.dumps(session))
    return p


def test_run_submit_importable_and_callable():
    from driftshield.cli._submit import run_submit
    assert callable(run_submit)


_OSS_TEST_INTAKE_URL = "https://intake.example.test/v1/oss/submissions"


def _remote_enable_argv(*, intake_url: str = _OSS_TEST_INTAKE_URL) -> list[str]:
    return ["telemetry", "remote-enable", "--intake-url", intake_url]


def test_submit_oss_inline_redacts_and_posts(tmp_path, monkeypatch):
    captured = {}

    def fake_post(*, config, submission):
        captured["intake_url"] = config.intake_url
        captured["request"] = submission

        class _Resp:
            submission_id = "sub_test"
            processing_status = "received"

        class _Result:
            response = _Resp()
            server_contract_version = None

        return _Result()

    monkeypatch.setattr("driftshield.cli._submit.post_oss_submission", fake_post)
    monkeypatch.setenv("DRIFTSHIELD_TELEMETRY_HOME", str(tmp_path / "tele"))
    session = _write_session(tmp_path)

    result = runner.invoke(app, ["submit", "--path", str(session)])
    assert result.exit_code == 0, result.output
    assert "sub_test" in result.output


def test_submit_appears_in_help():
    result = runner.invoke(app, ["--help"])
    assert "submit" in result.output


def test_submit_help_has_no_telemetry_framing():
    result = runner.invoke(app, ["submit", "--help"])
    assert result.exit_code == 0
    assert "telemetry" not in result.output.lower()


def _fake_post_ok(monkeypatch):
    """Return a fake_post callable that satisfies driftshield.cli._submit.post_oss_submission."""
    def fake_post(*, config, submission):
        class _Resp:
            submission_id = "sub_test"
            processing_status = "received"

        class _Result:
            response = _Resp()
            server_contract_version = None

        return _Result()

    return fake_post


def test_submit_session_hidden_from_help():
    result = runner.invoke(app, ["telemetry", "--help"])
    assert "submit-session" not in result.output


def test_submit_session_emits_deprecation(tmp_path, monkeypatch):
    # Use a local runner so we can inspect separated streams independently.
    # Click 8.2+ always separates stderr; CliRunner() needs no extra arguments.
    local_runner = CliRunner()
    monkeypatch.setattr("driftshield.cli._submit.post_oss_submission", _fake_post_ok(monkeypatch))
    monkeypatch.setenv("DRIFTSHIELD_TELEMETRY_HOME", str(tmp_path / "tele"))
    session = _write_session(tmp_path)
    result = local_runner.invoke(app, ["telemetry", "submit-session", "--path", str(session)])
    assert result.exit_code == 0, result.output
    # Deprecation notice must appear on stderr.
    assert "deprecated" in result.stderr.lower()
    assert "driftshield submit" in result.stderr
    # Stdout stays clean for scripting — no deprecation text on stdout.
    assert "deprecated" not in result.stdout.lower()


def test_submit_teams_tier_uses_authenticated_presigned_upload(tmp_path, monkeypatch):
    captured = {}

    def fake_teams_upload(*, config, payload, workflow_reference, file_name, provenance):
        captured["api_key"] = config.api_key
        captured["intake_url"] = config.intake_url

        class _Resp:
            submission_id = "sub_teams"
            processing_status = "received"

        class _Result:
            response = _Resp()
            server_contract_version = None

        return _Result()

    monkeypatch.setattr(
        "driftshield.cli._submit.submit_teams_via_presigned_upload", fake_teams_upload
    )
    monkeypatch.setenv("DRIFTSHIELD_API_KEY", "test-key")
    monkeypatch.setenv("DRIFTSHIELD_HOME", str(tmp_path))
    runner.invoke(app, _remote_enable_argv())
    session = _write_session(tmp_path)
    result = runner.invoke(app, ["submit", "--path", str(session), "--tier", "teams"])
    assert result.exit_code == 0, result.output
    assert captured["api_key"] == "test-key"
    assert "sub_teams" in result.output
